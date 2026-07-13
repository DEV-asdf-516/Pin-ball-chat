# Pinballchat

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
