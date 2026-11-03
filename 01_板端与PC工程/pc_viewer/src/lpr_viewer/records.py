"""PC 端车牌记录器：SQLite + 证据图，纯本地，不需要改开发板。

设计
----
* 只消费 GUI 已经拿到的 Frame 对象，不碰协议、不碰板端。
* 记录粒度是“一次通过”：同一车牌在 GAP 秒内再次出现只累加帧数；
  消失超过 GAP 秒后再出现才算新的一次。
* 证据图从预览 JPEG 里按 bbox 裁出来（预览已经缩放到 ≤640，精度够看车牌）。
* 依赖：Pillow + 标准库 sqlite3，不需要 opencv。
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS plate_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    first_ts    REAL    NOT NULL,
    last_ts     REAL    NOT NULL,
    day         TEXT    NOT NULL,
    plate       TEXT    NOT NULL,
    confidence  INTEGER NOT NULL,
    bbox        TEXT    NOT NULL,
    frames      INTEGER NOT NULL DEFAULT 1,
    frame_id    INTEGER,
    image       TEXT,
    snapshot    TEXT,
    src_w       INTEGER,
    src_h       INTEGER
);
CREATE INDEX IF NOT EXISTS idx_records_ts    ON plate_records(first_ts);
CREATE INDEX IF NOT EXISTS idx_records_plate ON plate_records(plate);
"""

DAY = "%Y-%m-%d"


def default_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "BluePlate7010" / "records"


class PlateRecorder:
    def __init__(self, root_dir=None, gap=5.0, keep_days=30, quality=90):
        self.root = Path(root_dir) if root_dir else default_root()
        self.images = self.root / "images"
        self.snapshots = self.root / "snapshots"
        self.db_path = self.root / "plates.db"
        self.gap = float(gap)
        self.keep_days = int(keep_days)
        self.quality = int(quality)

        self.images.mkdir(parents=True, exist_ok=True)
        self.snapshots.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._seq = 0
        self._active = {}          # plate -> {"id", "last_ts", "confidence"}
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self):
        """老库缺 snapshot 列时补上，避免升级后打不开。"""
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(plate_records)")}
        if "snapshot" not in columns:
            self._conn.execute("ALTER TABLE plate_records ADD COLUMN snapshot TEXT")

    # ------------------------------------------------------------------ 写入
    def observe(self, frame, snapshot=None):
        """喂一个 models.Frame。返回 (record_id, is_new)。

        snapshot: 整帧 JPEG 字节，识别成功时留一张"过车证据"，可为 None。
        """
        if getattr(frame, "state", None) != "PLATE":
            return None, False
        detections = getattr(frame, "detections", ()) or ()
        if not detections:
            return None, False

        det = detections[0]
        plate = str(getattr(det, "plate", "") or "").strip()
        if not plate:
            return None, False

        conf = int(getattr(det, "confidence_permille", 0) or 0)
        conf = max(0, min(1000, conf))
        bbox = tuple(int(v) for v in (getattr(det, "bbox_xyxy", None) or (0, 0, 0, 0)))
        now = time.time()

        with self._lock:
            active = self._active.get(plate)
            same_visit = active is not None and (now - active["last_ts"]) < self.gap

            if same_visit:
                better = conf > active["confidence"]
                image = self._save_evidence(frame, bbox, now) if better else None
                shot = self._save_snapshot(snapshot, now) if better else None
                if better:
                    self._conn.execute(
                        "UPDATE plate_records SET last_ts=?, confidence=?, bbox=?, frames=frames+1,"
                        " frame_id=?, image=COALESCE(?,image), snapshot=COALESCE(?,snapshot) WHERE id=?",
                        (now, conf, ",".join(map(str, bbox)), getattr(frame, "frame_id", None),
                         image, shot, active["id"]),
                    )
                    active["confidence"] = conf
                else:
                    self._conn.execute(
                        "UPDATE plate_records SET last_ts=?, frames=frames+1 WHERE id=?",
                        (now, active["id"]),
                    )
                active["last_ts"] = now
                self._conn.commit()
                return active["id"], False

            image = self._save_evidence(frame, bbox, now)
            shot = self._save_snapshot(snapshot, now)
            src = getattr(frame, "src_wh", (0, 0))
            cur = self._conn.execute(
                "INSERT INTO plate_records"
                " (first_ts,last_ts,day,plate,confidence,bbox,frames,frame_id,image,snapshot,src_w,src_h)"
                " VALUES (?,?,?,?,?,?,1,?,?,?,?,?)",
                (now, now, datetime.fromtimestamp(now).strftime(DAY), plate, conf,
                 ",".join(map(str, bbox)), getattr(frame, "frame_id", None), image, shot,
                 int(src[0]), int(src[1])),
            )
            self._conn.commit()
            record_id = int(cur.lastrowid)
            self._active[plate] = {"id": record_id, "last_ts": now, "confidence": conf}
            return record_id, True

    def _save_evidence(self, frame, bbox, now):
        """从预览图里裁出车牌区域；失败就存整张预览图。"""
        try:
            image = _frame_image(frame)
            if image is None:
                return None
            src_w, src_h = getattr(frame, "src_wh", (0, 0))
            view_w, view_h = getattr(frame, "view_wh", image.size)
            if src_w > 0 and src_h > 0:
                sx, sy = image.width / src_w, image.height / src_h
                x0, y0, x1, y1 = bbox
                mx = max(2, round((x1 - x0) * 0.08))
                my = max(2, round((y1 - y0) * 0.12))
                box = (max(0, round(x0 * sx) - mx), max(0, round(y0 * sy) - my),
                       min(image.width, round(x1 * sx) + mx),
                       min(image.height, round(y1 * sy) + my))
                if box[2] > box[0] and box[3] > box[1]:
                    image = image.crop(box)

            stamp = datetime.fromtimestamp(now)
            folder = self.images / stamp.strftime(DAY)
            folder.mkdir(parents=True, exist_ok=True)
            self._seq += 1
            name = "{}_{:06d}.jpg".format(stamp.strftime("%H%M%S"), self._seq % 1000000)
            target = folder / name
            tmp = target.with_suffix(".tmp")
            image.convert("RGB").save(tmp, "JPEG", quality=self.quality)
            os.replace(tmp, target)
            return str(target.relative_to(self.root)).replace(os.sep, "/")
        except Exception:
            return None

    def _save_snapshot(self, data, now):
        """整帧证据图：识别成功那一刻的画面，用于事后回看。"""
        if not data:
            return None
        try:
            stamp = datetime.fromtimestamp(now)
            folder = self.snapshots / stamp.strftime(DAY)
            folder.mkdir(parents=True, exist_ok=True)
            self._seq += 1
            name = "{}_full_{:06d}.jpg".format(stamp.strftime("%H%M%S"), self._seq % 1000000)
            target = folder / name
            tmp = target.with_suffix(".tmp")
            with open(tmp, "wb") as handle:
                handle.write(data)
            os.replace(tmp, target)
            return str(target.relative_to(self.root)).replace(os.sep, "/")
        except Exception:
            return None

    # ------------------------------------------------------------------ 查询
    def recent(self, limit=200, keyword=""):
        sql = ("SELECT id,first_ts,last_ts,plate,confidence,frames,image"
               " FROM plate_records")
        args = []
        if keyword:
            sql += " WHERE plate LIKE ?"
            args.append("%" + keyword + "%")
        sql += " ORDER BY last_ts DESC, id DESC LIMIT ?"
        args.append(int(limit))
        rows = self._conn.execute(sql, args).fetchall()
        return [
            {
                "id": r[0],
                "first": datetime.fromtimestamp(r[1]).strftime("%Y-%m-%d %H:%M:%S"),
                "last": datetime.fromtimestamp(r[2]).strftime("%H:%M:%S"),
                "plate": r[3],
                "confidence": round(r[4] / 10, 1),
                "frames": r[5],
                "image": str(self.root / r[6]) if r[6] else None,
            }
            for r in rows
        ]

    def daily_stats(self, days=7):
        since = time.time() - days * 86400
        rows = self._conn.execute(
            "SELECT day,COUNT(*),SUM(frames) FROM plate_records"
            " WHERE first_ts>=? GROUP BY day ORDER BY day DESC", (since,)
        ).fetchall()
        return [{"day": r[0], "plates": r[1], "frames": r[2] or 0} for r in rows]

    def total(self):
        return self._conn.execute("SELECT COUNT(*) FROM plate_records").fetchone()[0]

    def hourly(self, day=None):
        """今天每个小时识别到几次，返回 24 个整数。"""
        day = day or datetime.now().strftime(DAY)
        rows = self._conn.execute(
            "SELECT first_ts FROM plate_records WHERE day=?", (day,)
        ).fetchall()
        buckets = [0] * 24
        for (ts,) in rows:
            buckets[datetime.fromtimestamp(ts).hour] += 1
        return buckets

    def daily(self, days=7):
        """最近 days 天（含今天）每天几次，返回 [(日期, 次数)]。"""
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        out = []
        for offset in range(days - 1, -1, -1):
            day = (today - timedelta(days=offset)).strftime(DAY)
            count = self._conn.execute(
                "SELECT COUNT(*) FROM plate_records WHERE day=?", (day,)
            ).fetchone()[0]
            out.append((day[5:], count))
        return out

    def top_plates(self, limit=5):
        rows = self._conn.execute(
            "SELECT plate, COUNT(*) FROM plate_records GROUP BY plate"
            " ORDER BY COUNT(*) DESC, MAX(first_ts) DESC LIMIT ?", (int(limit),)
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def export_csv(self, path):
        import csv
        rows = self._conn.execute(
            "SELECT first_ts,last_ts,plate,confidence,frames,bbox,image"
            " FROM plate_records ORDER BY first_ts"
        ).fetchall()
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["首次时间", "最近时间", "车牌", "置信度%", "帧数", "包围框", "证据图"])
            for r in rows:
                w.writerow([
                    datetime.fromtimestamp(r[0]).strftime("%Y-%m-%d %H:%M:%S"),
                    datetime.fromtimestamp(r[1]).strftime("%Y-%m-%d %H:%M:%S"),
                    r[2], round(r[3] / 10, 1), r[4], r[5],
                    str(self.root / r[6]) if r[6] else "",
                ])
        return len(rows)

    # ------------------------------------------------------------------ 维护
    def prune(self, keep_days=None):
        keep = self.keep_days if keep_days is None else int(keep_days)
        cutoff = time.time() - keep * 86400
        rows = self._conn.execute(
            "SELECT id,image,snapshot FROM plate_records WHERE first_ts<?", (cutoff,)
        ).fetchall()
        for _id, image, snapshot in rows:
            for rel in (image, snapshot):
                if not rel:
                    continue
                try:
                    (self.root / rel).unlink()
                except OSError:
                    pass
        self._conn.execute("DELETE FROM plate_records WHERE first_ts<?", (cutoff,))
        self._conn.commit()
        return len(rows)

    def close(self):
        with self._lock:
            try:
                self._conn.commit()
            finally:
                self._conn.close()


def _frame_image(frame):
    """把 Frame 里的图像数据还原成 PIL Image（支持 jpeg 与 gray8）。"""
    from PIL import Image

    data = getattr(frame, "image_data", None)
    if not data:
        return None
    codec = getattr(frame, "codec", "jpeg")
    if codec == "jpeg":
        with Image.open(BytesIO(data)) as img:
            return img.convert("RGB")
    size = getattr(frame, "view_wh", None)
    if not size:
        return None
    return Image.frombytes("L", tuple(size), data).convert("RGB")


if __name__ == "__main__":
    # 自测：造一张假预览图，同车牌 4 帧 + 换车牌 1 帧，应为 2 条记录
    import shutil
    from types import SimpleNamespace

    from PIL import Image, ImageDraw

    tmp = Path(__file__).with_name("_selftest")
    shutil.rmtree(tmp, ignore_errors=True)

    preview = Image.new("RGB", (320, 240), (20, 20, 20))
    draw = ImageDraw.Draw(preview)
    draw.rectangle((24, 45, 104, 75), fill=(0, 60, 200))       # 车牌区域（预览坐标）
    for i in range(7):
        draw.text((28 + i * 11, 52), "A", fill=(255, 255, 255))
    buf = BytesIO()
    preview.save(buf, "JPEG", quality=90)
    jpeg = buf.getvalue()

    def make(plate, conf, fid):
        return SimpleNamespace(
            frame_id=fid, capture_ms=0, src_wh=(800, 480), view_wh=(320, 240),
            codec="jpeg", state="PLATE",
            detections=[SimpleNamespace(bbox_xyxy=(60, 90, 260, 150),
                                        plate=plate, confidence_permille=conf)],
            image_data=jpeg,
        )

    rec = PlateRecorder(tmp, gap=5.0)
    try:
        results = [rec.observe(make("京A12345", conf, i))
                   for i, conf in enumerate((700, 810, 860, 840))]
        rec.observe(make("京B67890", 900, 9))

        rows = rec.recent()
        assert len(rows) == 2, rows
        got = {r["plate"]: r for r in rows}
        assert got["京A12345"]["confidence"] == 86.0, got
        assert got["京A12345"]["frames"] == 4, got
        assert got["京B67890"]["frames"] == 1, got
        assert results[0][1] is True and all(not new for _, new in results[1:])

        evidence = Path(got["京A12345"]["image"])
        assert evidence.exists(), evidence
        with Image.open(evidence) as img:
            assert img.width < 320, img.size          # 确实裁过
            print("证据图尺寸:", img.size)

        assert rec.export_csv(tmp / "out.csv") == 2
        assert rec.total() == 2
        print("自测通过：", [(r["plate"], r["confidence"], r["frames"]) for r in rows])
    finally:
        rec.close()
        shutil.rmtree(tmp, ignore_errors=True)

