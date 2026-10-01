// 팀 공유 설정. 비워 두면 데모 모드(이 브라우저에만 저장)로 동작합니다.
// Firebase 웹 설정값은 공개되어도 괜찮은 값이며, 실제 접근 제어는 firestore.rules 가 담당합니다.
window.APP_CONFIG = {
  firebase: {
    apiKey: "AIzaSyAQiexeVdj5k06UmAX6pGEOhD-v5taQDUU",
    authDomain: "app-review-dashboard-7dd3d.firebaseapp.com",
    projectId: "app-review-dashboard-7dd3d",
    appId: "1:760661310068:web:b03b72fdcbe4d8de47ef21",
  },
  github: {
    owner: "FHsimpson",   // GitHub 사용자명
    repo: "app-review-dashboard",
    branch: "main",
    workflow: "collect.yml",
  },
};
