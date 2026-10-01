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

    def meta(self, data):
        self.db.collection("meta").document("lastRun").set(data, merge=True)

    def members(self, admins):
        ref = self.db.collection("config").document("members")
        ref.set({"emails": self.fs.ArrayUnion(admins), "admins": self.fs.ArrayUnion(admins)}, merge=True)

    def close(self):
        pass


# ---------------------------------------------------------------- 병합
def merge(store, incoming, seed=False):
    ex = store.existing()
    sigs = {signature(r): did for did, r in ex.items()}
    added, upgraded, stamp = [], 0, today()
    for r in incoming:
        did = r.get("id") or doc_id(r["app"], r["store"], r["rid"])
        if did in ex:
            continue
        s = signature(r)
        if s in sigs:
            # 같은 리뷰가 다른 경로로 이미 들어와 있으면 비어 있는 필드만 채움
            old = ex[sigs[s]]
            fill = {k: r[k] for k in ("rating", "version", "author") if r.get(k) and not old.get(k)}
            if fill:
                store.update(sigs[s], fill)
                old.update(fill)
                upgraded += 1
            continue
        doc = dict(r, id=did, collectedAt=r.get("collectedAt") or stamp, seed=bool(seed or r.get("seed")))
        added.append(doc)
        ex[did] = doc
        sigs[s] = did
    store.add(added)
    return added, upgraded


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
        added, counts, errors, upgraded = [], {}, [], 0
        if not a.no_fetch:
            fetched, counts, errors = fetch_all()
            added, upgraded = merge(store, fetched)
        by = {}
        for d in added:
            k = f"{d['app']}_{d['store']}"
            by[k] = by.get(k, 0) + 1
        failed = [k for k, v in counts.items() if v == 0]
        store.meta({"status": "done", "startedAt": started,
                    "finishedAt": datetime.now(KST).isoformat(timespec="seconds"),
                    "date": today(), "added": len(added), "addedBy": by, "fetched": counts,
                    "failed": failed, "upgraded": upgraded, "errors": errors[:5], "trigger": a.trigger})
        print(f"신규 {len(added)}건 {by} / 보강 {upgraded}건 / 조회 실패 {failed}")
    except Exception as e:
        store.meta({"status": "error", "finishedAt": datetime.now(KST).isoformat(timespec="seconds"),
                    "errors": [str(e)[:300]], "trigger": a.trigger})
        raise
    finally:
        store.close()


if __name__ == "__main__":
    main()
