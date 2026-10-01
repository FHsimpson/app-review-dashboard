# 앱 리뷰 확인판

노스페이스 코리아 / 스케쳐스 코리아 앱의 Google Play·App Store 리뷰를 모아
팀원이 함께 **확인 상태(미확인·확인중·확인완료·해당없음)** 와 메모를 관리하는 페이지입니다.

- 평일 09:05(KST)에 자동으로 새 리뷰를 가져옵니다. PC가 꺼져 있어도 됩니다.
- 페이지의 **[리뷰 최신화]** 버튼으로 언제든 바로 가져올 수 있습니다.
- 운영에 Claude가 필요 없습니다. 비용도 무료입니다 (GitHub 공개 저장소 + Firebase 무료 요금제).

## 구성

| 부분 | 하는 일 | 위치 |
|---|---|---|
| 페이지 | 탭별 리뷰, 우선 개선 항목, 확인 상태·메모 | `docs/index.html` → GitHub Pages |
| 데이터 | 리뷰, 확인 상태, 팀원 목록 | Firebase Firestore |
| 로그인 | 등록된 Google 계정만 접근 | Firebase Authentication |
| 수집기 | 스토어에서 새 리뷰를 가져와 저장 | `collector/collect.py` → GitHub Actions |

[리뷰 최신화]를 누르면 GitHub Actions의 수집 작업이 실행되고, 1~3분 뒤 새 리뷰가 페이지에 자동으로 나타납니다.

## 설정 순서 (처음 한 번, 약 30분)

### 1. GitHub 저장소
1. GitHub에 로그인하고 **Public** 저장소 `app-review-dashboard` 를 만듭니다.
   (무료 계정에서 GitHub Pages를 쓰려면 공개 저장소여야 합니다. 저장소에는 코드와 공개 리뷰만 올라가고, 확인 상태·메모는 Firebase에 로그인한 팀원만 볼 수 있습니다.)
2. 이 폴더의 파일을 모두 올립니다. `.github` 폴더도 꼭 포함해야 합니다.

### 2. Firebase 프로젝트
1. https://console.firebase.google.com 에서 프로젝트를 만듭니다 (Google Analytics 는 꺼도 됩니다).
2. **Authentication → 시작하기 → 로그인 방법 → Google** 을 사용 설정합니다.
3. **Authentication → 설정 → 승인된 도메인** 에 `<GitHub사용자명>.github.io` 를 추가합니다.
4. **Firestore Database → 데이터베이스 만들기** → 위치 `asia-northeast3 (서울)` → 프로덕션 모드.
5. **Firestore → 규칙** 탭에 `firestore.rules` 내용을 붙여넣고 게시합니다.
6. **프로젝트 설정(톱니바퀴) → 일반 → 내 앱 → 웹 앱 추가(</>)** 후 나오는 `apiKey, authDomain, projectId, appId` 를
   `docs/config.js` 에 넣고, 같은 파일의 `github.owner` 에 GitHub 사용자명을 넣습니다.

### 3. 수집기 권한 연결
1. Firebase **프로젝트 설정 → 서비스 계정 → 새 비공개 키 생성** 으로 JSON 파일을 받습니다.
2. GitHub 저장소 **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `FIREBASE_SERVICE_ACCOUNT`
   - Secret: 받은 JSON 파일 내용 전체
3. 받은 JSON 파일은 삭제합니다. 이 키로 데이터베이스 전체를 쓸 수 있으니 채팅이나 메일로 공유하지 마세요.

### 4. 페이지 공개
GitHub 저장소 **Settings → Pages → Build and deployment**: Source `Deploy from a branch`, Branch `main` / 폴더 `/docs` → Save.
몇 분 뒤 `https://<GitHub사용자명>.github.io/app-review-dashboard/` 에서 열립니다.

### 5. 최초 설정 실행
GitHub 저장소 **Actions → 최초 설정 (1회) → Run workflow** 에 관리자 Google 이메일을 넣고 실행합니다.
기존에 모은 리뷰 163건이 들어가고, 스토어에서 최신 리뷰도 한 번 가져옵니다.

### 6. [리뷰 최신화] 버튼 연결
1. GitHub **Settings(개인) → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
   - Repository access: `Only select repositories` → `app-review-dashboard`
   - Permissions → Repository permissions → **Actions: Read and write** (다른 권한은 주지 않습니다)
   - Expiration: 원하는 기간 (만료되면 새로 만들어 다시 등록)
2. 대시보드에 관리자 계정으로 로그인 → **설정** → 토큰 붙여넣기 → 저장.

### 7. 팀원 추가
대시보드 **설정 → 팀원** 에 팀원의 Google 이메일을 추가합니다. 팀원은 페이지 주소로 들어와 Google 로그인만 하면 됩니다.

## 사용 방법
- 상단 탭으로 앱을 고릅니다. 탭의 큰 숫자는 아직 아무도 확인하지 않은 이슈 리뷰 수입니다.
- 리뷰마다 **미확인 / 확인중 / 확인완료 / 해당없음** 을 누르면 팀 전체에 바로 반영되고, 누가 언제 바꿨는지 표시됩니다.
- **우선 개선 항목** 은 이슈 리뷰를 유형별로 묶은 것입니다. 항목 단위로도 상태와 메모를 남길 수 있고, `관련 리뷰 보기` 로 해당 리뷰만 걸러 볼 수 있습니다.

## 자주 묻는 것
- **자동 수집 시각이 조금 늦어요**: GitHub 예약 실행은 몇 분~수십 분 늦게 시작될 수 있습니다. 급하면 [리뷰 최신화]를 누르세요.
- **"일부 스토어 조회 실패"가 떠요**: 스토어 측 변경 가능성이 있습니다. Actions 탭의 실행 기록에서 오류 내용을 확인하세요.
  App Store 는 웹페이지용 리뷰 API를, 실패하면 공개 RSS 를 씁니다.
- **분류 기준을 바꾸고 싶어요**: `docs/index.html` 의 `NEGATIVE`, `ISSUES` 를 수정하면 기존 리뷰에도 바로 적용됩니다.
- **로컬에서 미리 보기**: `docs/index.html` 을 브라우저로 열면 데모 모드로 동작합니다 (상태는 그 브라우저에만 저장).
- **무료 한도**: Firestore 무료 요금제는 하루 읽기 5만 건입니다. 팀 10명 정도가 하루 여러 번 열어도 충분합니다.
