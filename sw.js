// 진짜 앱으로 인식시키기 위한 필수 통과용 코드입니다.
self.addEventListener('install', (e) => {
  console.log('앱 설치 완료');
});

self.addEventListener('fetch', (e) => {
  // 오프라인 작동 등 복잡한 기능은 생략하고 통과만 시킵니다.
});
