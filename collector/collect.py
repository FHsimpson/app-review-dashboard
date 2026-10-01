#!/usr/bin/env python3
"""
앱 리뷰 수집기 (노스페이스 코리아 / 스케쳐스 코리아)

- Google Play : google-play-scraper, 최신순 전체
- App Store   : apps.apple.com 웹페이지가 쓰는 리뷰 API (별점 포함 전체), 실패 시 RSS
- 저장        : Firestore(reviews 컬렉션) 또는 로컬 JSON(--json)
- 이슈/카테고리 분류는 대시보드에서 계산하므로 여기서는 원본만 저장

사용:
  python collect.py                                   # Firestore 에 신규 리뷰 추가 (env FIREBASE_SERVICE_ACCOUNT)
  python collect.py --json out.json                   # 로컬 JSON 으로 수집 (테스트용)
  python collect.py --seed ../seed/reviews_seed.json --admins a@x.com   # 최초 1회 설정
"""
import argparse, hashlib, json, os, sys, time
from datetime import datetime, timezone, timedelta

import requests

KST = timezone(timedelta(hours=9))
APPS = {
    "nf": {"name": "노스페이스 코리아", "play": "kr.co.thenorthfacekorea.app", "ios": "6450890314"},
    "sk": {"name": "스케쳐스 코리아",   "play": "kr.co.skecherskorea.app",     "ios": "6754304244"},
}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


def today():
    return datetime.now(KST).strftime("%Y-%m-%d")


def doc_id(app, store, rid):
    return hashlib.sha1(f"{app}|{store}|{rid}".encode()).hexdigest()[:24]


def signature(r):
    """다른 경로로 수집된 같은 리뷰를 걸러내기 위한 서명 (앱, 스토어, 작성일, 제목+본문 앞 40자)."""
    body = "".join(((r.get("title") or "") + (r.get("text") or "")).split())
    return f"{r['app']}|{r['store']}|{r.get('date', '')}|{body[:40]}"


# ---------------------------------------------------------------- Google Play
def fetch_play(app):
    from google_play_scraper import Sort, reviews
    out, token = [], None
    for _ in range(50):  # 최대 10,000건
        result, token = reviews(APPS[app]["play"], lang="ko", country="kr", sort=Sort.NEWEST,
                                count=200, continuation_token=token)
        for r in result:
            at = r["at"]
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            out.append({
                "app": app, "store": "play", "rid": r["reviewId"],
                "date": at.astimezone(KST).strftime("%Y-%m-%d"),
                "rating": r["score"], "title": "", "text": (r["content"] or "").strip(),
                "author": r["userName"] or "", "version": r.get("reviewCreatedVersion") or "",
                "reply": bool(r.get("replyContent")),
            })
        if not result or not token or not getattr(token, "token", None):
            break
    return out


# ---------------------------------------------------------------- App Store
def fetch_ios(app):
    """apps.apple.com 리뷰 API. 페이지당 20건씩 offset 으로 끝까지 조회."""
    app_id = APPS[app]["ios"]
    base = f"https://apps.apple.com/api/apps/v1/catalog/kr/apps/{app_id}/reviews"
    headers = {"User-Agent": UA, "Accept": "application/json",
               "Referer": f"https://apps.apple.com/kr/app/id{app_id}?see-all=reviews&platform=iphone"}
    out, offset, retries = [], 0, 0
    while offset < 2000:
        resp = requests.get(base, params={"l": "ko", "platform": "iphone", "limit": 20, "offset": offset},
                            headers=headers, timeout=30)
        if resp.status_code == 429 and retries < 5:  # 요청 과다: 잠시 쉬고 재시도
            retries += 1
            time.sleep(5 * retries)
            continue
        resp.raise_for_status()
        j = resp.json()
        data = j.get("data") or []
        for d in data:
            a = d.get("attributes", {})
            out.append({
                "app": app, "store": "ios", "rid": str(d["id"]),
                "date": (a.get("date") or "")[:10], "rating": a.get("rating"),
                "title": (a.get("title") or "").strip(), "text": (a.get("review") or "").strip(),
                "author": a.get("userName") or "", "version": "",
                "reply": bool(a.get("developerResponse")),
            })
        if not data or not j.get("next"):
            break
        offset += len(data)
        retries = 0
        time.sleep(1.2)
    return out


def fetch_ios_rss(app):
    """예비 경로: 공개 RSS (한국 스토어는 비어 있는 경우가 많음)."""
    out = []
    for page in range(1, 11):
        url = (f"https://itunes.apple.com/kr/rss/customerreviews/page={page}/"
               f"id={APPS[app]['ios']}/sortby=mostrecent/json")
        entries = requests.get(url, timeout=20, headers={"User-Agent": UA}).json() \
            .get("feed", {}).get("entry", [])
        if isinstance(entries, dict):
            entries = [entries]
        entries = [e for e in entries if "im:rating" in e]
        if not entries:
            break
        for e in entries:
            out.append({
                "app": app, "store": "ios", "rid": e["id"]["label"],
                "date": e["updated"]["label"][:10], "rating": int(e["im:rating"]["label"]),
                "title": e["title"]["label"].strip(), "text": e["content"]["label"].strip(),
                "author": e["author"]["name"]["label"], "version": e.get("im:version", {}).get("label", ""),
                "reply": False,
            })
    return out


def fetch_all():
    results, counts, errors = [], {}, []
    for app in APPS:
        for store, fns in (("play", [fetch_play]), ("ios", [fetch_ios, fetch_ios_rss])):
            got = []
            for fn in fns:
                try:
                    got = fn(app)
                    if got:
                        break
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{app}/{store}/{fn.__name__}: {str(e)[:200]}")
                    print(f"[warn] {app}/{store}/{fn.__name__}: {e}", file=sys.stderr)
            counts[f"{app}_{store}"] = len(got)
            print(f"  {APPS[app]['name']} / {store}: {len(got)}건 조회")
            results += got
    return results, counts, errors


# ---------------------------------------------------------------- 저장소
class JsonStore:
    def __init__(self, path):
        self.path = path
        self.rows = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []

    def existing(self):
        return {r["id"]: r for r in self.rows}

    def add(self, docs):
        self.rows += docs

    def update(self, did, fields):
        for r in self.rows:
            if r["id"] == did:
                r.update(fields)

    def delete(self, did, move_status_to=None):
        self.rows = [r for r in self.rows if r["id"] != did]

    def meta(self, data):
        print("[meta]", json.dumps(data, ensure_ascii=False))

    def members(self, admins):
        pass

    def close(self):
        json.dump(self.rows, open(self.path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


class FirestoreStore:
    def __init__(self):
        import firebase_admin
        from firebase_admin import credentials, firestore
        raw = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
        if not raw:
            sys.exit("FIREBASE_SERVICE_ACCOUNT 환경변수(서비스 계정 JSON)가 없습니다. GitHub Secret 을 확인하세요.")
        firebase_admin.initialize_app(credentials.Certificate(json.loads(raw)))
        self.fs = firestore
        self.db = firestore.client()

    def existing(self):
        return {d.id: d.to_dict() for d in self.db.collection("reviews").stream()}

    def add(self, docs):
        for i in range(0, len(docs), 400):
            b = self.db.batch()
            for d in docs[i:i + 400]:
                b.set(self.db.collection("reviews").document(d["id"]), {k: v for k, v in d.items() if k != "id"})
            b.commit()

    def update(self, did, fields):
        self.db.collection("reviews").document(did).update(fields)

    def delete(self, did, move_status_to=None):
        if move_status_to:
            src = self.db.collection("status").document(did)
            snap = src.get()
            dst = self.db.collection("status").document(move_status_to)
            if snap.exists and not dst.get().exists:
                dst.set(snap.to_dict())
            if snap.exists:
                src.delete()
        self.db.collection("reviews").document(did).delete()

    def meta(self, data):
        self.db.collection("meta").document("lastRun").set(data, merge=True)

    def members(self, admins):
        ref = self.db.collection("config").document("members")
        ref.set({"emails": self.fs.ArrayUnion(admins), "admins": self.fs.ArrayUnion(admins)}, merge=True)

    def close(self):
        pass


# ---------------------------------------------------------------- 병합
def body_key(r):
    body = "".join(((r.get("title") or "") + (r.get("text") or "")).split())
    return f"{r['app']}|{r['store']}|{body[:40]}"


def days_apart(a, b):
    try:
        return abs((datetime.fromisoformat(a) - datetime.fromisoformat(b)).days)
    except Exception:  # noqa: BLE001
        return 99


def same_review(a, b):
    """본문이 같고, 작성일이 2일 이내이며, 작성자가 같거나 한쪽이 비어 있으면 같은 리뷰로 본다.
    (Play 웹 화면과 수집기의 시간대 기준이 달라 날짜가 하루 어긋나는 경우가 있음)"""
    if days_apart(a.get("date", ""), b.get("date", "")) > 2:
        return False
    au, bu = (a.get("author") or "").strip(), (b.get("author") or "").strip()
    return not au or not bu or au == bu


def merge(store, incoming, seed=False):
    ex = store.existing()
    idx = {}
    for did, r in ex.items():
        idx.setdefault(body_key(r), []).append(did)
    added, upgraded, stamp = [], 0, today()
    for r in incoming:
        did = r.get("id") or doc_id(r["app"], r["store"], r["rid"])
        if did in ex:
            continue
        match = next((m for m in idx.get(body_key(r), []) if same_review(ex[m], r)), None)
        if match:
            # 같은 리뷰가 다른 경로로 이미 들어와 있으면 비어 있는 필드만 채움
            old = ex[match]
            fill = {k: r[k] for k in ("rating", "version", "author") if r.get(k) and not old.get(k)}
            if fill:
                store.update(match, fill)
                old.update(fill)
                upgraded += 1
            continue
        doc = dict(r, id=did, collectedAt=r.get("collectedAt") or stamp, seed=bool(seed or r.get("seed")))
        added.append(doc)
        ex[did] = doc
        idx.setdefault(body_key(doc), []).append(did)
    store.add(added)
    return added, upgraded


def dedupe(store):
    """이미 저장된 중복 정리: 같은 리뷰가 두 번 있으면 브라우저로 모은 사본(seed)을 지우고
    스토어에서 직접 받은 쪽을 남긴다. 사본에 남긴 확인 상태는 남는 쪽으로 옮긴다."""
    ex = store.existing()
    groups = {}
    for did, r in ex.items():
        groups.setdefault(body_key(r), []).append(did)
    removed = 0
    for ids in groups.values():
        if len(ids) < 2:
            continue
        real = [i for i in ids if not ex[i].get("seed")]
        for sid in [i for i in ids if ex[i].get("seed")]:
            keep = next((k for k in real if same_review(ex[k], ex[sid])), None)
            if keep:
                store.delete(sid, move_status_to=keep)
                removed += 1
    return removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="Firestore 대신 로컬 JSON 파일에 저장")
    ap.add_argument("--seed", help="기존 수집 데이터(JSON)를 먼저 넣기")
    ap.add_argument("--admins", default="", help="관리자 이메일(쉼표 구분)")
    ap.add_argument("--no-fetch", action="store_true", help="스토어 조회 없이 seed/관리자만 반영")
    ap.add_argument("--trigger", default=os.environ.get("TRIGGER", "manual"))
    a = ap.parse_args()

    store = JsonStore(a.json) if a.json else FirestoreStore()
    started = datetime.now(KST).isoformat(timespec="seconds")
    store.meta({"status": "running", "startedAt": started, "trigger": a.trigger})
    try:
        if a.admins:
            admins = [e.strip().lower() for e in a.admins.split(",") if e.strip()]
            store.members(admins)
            print(f"관리자 등록: {admins}")
        if a.seed:
            seed_added, _ = merge(store, json.load(open(a.seed, encoding="utf-8")), seed=True)
            print(f"기존 데이터 반영: {len(seed_added)}건")
        added, counts, errors, upgraded, removed = [], {}, [], 0, 0
        if not a.no_fetch:
            fetched, counts, errors = fetch_all()
            added, upgraded = merge(store, fetched)
        removed = dedupe(store)
        if removed:
            print(f"중복 정리: {removed}건")
        by = {}
        for d in added:
            k = f"{d['app']}_{d['store']}"
            by[k] = by.get(k, 0) + 1
        failed = [k for k, v in counts.items() if v == 0]
        store.meta({"status": "done", "startedAt": started,
                    "finishedAt": datetime.now(KST).isoformat(timespec="seconds"),
                    "date": today(), "added": len(added), "addedBy": by, "fetched": counts,
                    "failed": failed, "upgraded": upgraded, "deduped": removed if not a.no_fetch else 0, "errors": errors[:5], "trigger": a.trigger})
        print(f"신규 {len(added)}건 {by} / 보강 {upgraded}건 / 조회 실패 {failed}")
    except Exception as e:
        store.meta({"status": "error", "finishedAt": datetime.now(KST).isoformat(timespec="seconds"),
                    "errors": [str(e)[:300]], "trigger": a.trigger})
        raise
    finally:
        store.close()


if __name__ == "__main__":
    main()
