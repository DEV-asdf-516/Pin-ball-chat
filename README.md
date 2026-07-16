# Pinballchat


> [!NOTE]
> 스캐터랩의 Zeta에서 영감을 받아 개발 중인 1인용 캐릭터 AI 채팅 시스템입니다.<br/>

> [!IMPORTANT]
> 어디까지나 개인적인 연구와 구현을 위한 프로젝트이며, *__공개 서비스 운영이나 배포를 목적으로 하지 않습니다.__*<br/>
> 본 프로젝트는 스캐터랩 및 Zeta와 공식적인 관련이 없는 비공식 개인 프로젝트입니다.

Zeta를 만든 스캐터랩 팀에 감사와 존중을 표합니다.


## 프론트 실행

repo 루트에서 웹과 API를 함께 띄운다.

```bash
docker compose up web api
```

브라우저에서 접속:

```text
http://localhost:3000
```

기본 API 주소는 `http://localhost:8080`이다.

API를 이미 따로 실행 중이면 웹만 띄워도 된다.

```bash
docker compose up web
```

정적 파일은 bind mount라 보통 브라우저 새로고침만 하면 수정사항이 반영된다.
