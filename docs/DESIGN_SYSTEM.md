# Ember design notes

원본 브랜드/레이아웃을 그대로 복제하지 않고, 공개 Figma·제품 디자인 시스템의 관제 대시보드 패턴을 참고해 새 UI를 구현했습니다. Figma 파일을 생성하거나 수정한 것은 아닙니다.

참고한 공개 자료:

- [Figma dashboard templates](https://www.figma.com/templates/dashboard-designs/): sidebar·summary·signal panel 등 정보 구조.
- [Figma design system examples](https://www.figma.com/resource-library/design-system-examples/): 재사용 토큰과 컴포넌트 일관성.
- [Carbon design resources](https://www.carbondesignsystem.com/getting-started/designing/design-resources): 상태/정보 밀도/접근성 중심 시스템.
- [shadcn dashboard](https://ui.shadcn.com/examples/dashboard): 작은 컨트롤과 모듈형 panel 패턴.

사용한 표현은 밝은 회색 바탕, 짙은 녹색 primary, 따뜻한 주황 fire, 낮은 채도의 보조 색입니다. 숫자·상태를 우선하고 장식 차트나 가짜 카메라 통계를 넣지 않았습니다. 자체 SVG 등고선은 빈 관측 지점 화면의 장식이며 실제 지리 정보가 아닙니다.

React 컴포넌트는 Brand, Badge, Modal, CameraCard, EventRow로 나눴습니다. 반응형 sidebar·카메라 grid·휴대폰 전송 화면을 구현했고, modal focus trap/Escape, focus-visible, reduced-motion, 상태 텍스트와 아이콘을 함께 제공합니다. 소스 스타일은 `frontend/src/styles.css`입니다. UI 폰트는 시스템 폰트이며 외부 폰트 요청을 하지 않습니다.

정식 WCAG 접근성 검수, 실제 휴대폰 밝은 야외 환경 테스트, 모든 브라우저 조합 검증은 아직 하지 않았습니다.
