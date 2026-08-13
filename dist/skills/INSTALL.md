# Orange Check 설치

**패키지는 하나다.** 네 플랫폼이 같은 스킬을 쓴다. 환경마다 되는 일이 다른 부분은
스킬이 시작할 때 스스로 확인하고 맞춰 움직인다.

## 어떻게 부르나

| 환경 | 부르는 법 |
|---|---|
| Claude Code | `/orange-check` |
| OpenAI Codex | `$orange-check` |
| Claude 앱 (Cowork·claude.ai) | 스킬을 켜 두면 요청 내용을 보고 알아서 발동한다 |
| ChatGPT for Work | 지침에 넣어 두면 요청 내용을 보고 알아서 발동한다 |

Claude Code와 Codex 모두 **폴더 이름이 곧 부르는 이름**이다. `orange-check` 폴더를
그대로 두어야 `/orange-check`·`$orange-check`으로 불린다. 폴더 이름을 바꾸면
부르는 이름도 따라 바뀐다.

이름을 대지 않아도 된다. "이 문서 참고문헌 검증해줘"처럼 요청하면 스킬 설명을 보고
알아서 발동한다. 확실히 부르고 싶을 때만 위 표를 쓴다.

## Claude 앱 (Cowork · claude.ai · 데스크톱)

1. 설정 → 기능 → **코드 실행 및 파일 생성**을 켠다. (최초 1회)
2. Cowork → 맞춤설정 → 스킬 → **＋** → **스킬 업로드**.
3. `orange-check.zip`을 고르고, 목록에 나타나면 **토글을 켠다**.
4. 하위 스킬도 쓰려면 `orange-check-extract.zip` 등을 같은 방법으로 각각 올린다.

## Claude Code (CLI · 데스크톱 앱)

```bash
unzip orange-check-all.zip -d /tmp/oc && mkdir -p ~/.claude/skills
cp -R /tmp/oc/orange-check* ~/.claude/skills/
```

프로젝트 한정으로 쓰려면 `.claude/skills/` 아래에 둔다.
설치하면 `/orange-check`으로 부를 수 있고, 하위 스킬은 `/orange-check-extract` 식이다.

## OpenAI Codex (CLI · IDE · 클라우드)

```bash
unzip orange-check-all.zip -d /tmp/oc && mkdir -p ~/.codex/skills
cp -R /tmp/oc/orange-check* ~/.codex/skills/
```

설치하면 `$orange-check`으로 부를 수 있고, 하위 스킬은 `$orange-check-extract` 식이다.
`/skills` 를 치면 설치된 목록이 나온다. 프로젝트 한정으로 쓰려면 `.codex/skills/` 아래에 둔다.

샌드박스가 기본으로 네트워크를 막는다. 원문 PDF를 받아야 하면 네트워크 접근을
허용하고 실행하라. 막힌 채로도 동작하되, 스킬이 사용자에게 원문을 요청하는 방식으로 물러선다.

## ChatGPT for Work (Business · Enterprise)

1. `orange-check-all.zip`을 풀고 `orange-check/SKILL.md`의 내용을 프로젝트 지침
   (또는 커스텀 GPT 지침)에 붙여 넣는다.
2. `orange-check/scripts/` 폴더를 프로젝트 파일 또는 지식 파일로 올린다.
3. 검증할 문서와 **출처 원문 PDF를 함께** 첨부한다.

> 이 환경은 코드 실행이 인터넷에 나갈 수 없다. 스킬이 원문을 스스로 받아 올 수 없으므로,
> 필요한 원문 목록을 한 번에 요청하고 올라오지 않은 출처는 '근거 부족'으로 남긴다.
> 서지 실존 확인은 모델의 웹 검색으로 대체로 가능하다.

## 한글 문서를 다룬다면 (선택)

[kordoc](https://github.com/chrisryugj/kordoc)이 있으면 표를 구조로 살리고 쪽 번호가
붙으며, HWP 3.x·배포용 문서처럼 순수 파이썬이 못 여는 형식까지 열린다.
Node가 있는 환경(Claude Code·Codex)에서 설치 없이 바로 쓸 수 있다.

```bash
npx -y kordoc@latest --help     # 설치 불필요
```

없어도 된다. 없으면 표준 라이브러리만으로 읽는다 — 실측 1,267건 중 93.4%가 열린다.


## 들어 있는 스킬

- `orange-check/`
- `orange-check-extract/`
- `orange-check-judge/`
- `orange-check-support/`
