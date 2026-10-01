# 서울대학교 eTL 학습 도우미

`snu-myetl-skill`은 서울대학교 eTL의 Canvas API와 Codex를 연결해, 자연어로 수강 정보를 조회하고 학습 자료를 정리하는 공유·제출용 스킬입니다. 개강 때 과목별 폴더와 강의계획서를 준비하고, 학기 중에는 새 자료·공지·과제 일정을 이어서 확인하는 데 사용합니다.

## 무엇을 할 수 있나요?

| 사용자가 부탁하는 일 | 스킬이 수행하는 흐름 |
|---|---|
| 이번 학기 수업 폴더 만들기 | 수강 과목을 조회하고 사용자가 지정한 학기 폴더 안에 과목별 폴더 생성 |
| 실래버스 모으기 | 강의계획서 본문과 첨부자료를 찾아 과목별로 저장 |
| 이번 학기 한눈에 보기 | 실래버스를 읽어 교수·조교 연락처, 연구실, 오피스아워, 교재, 평가 비중을 출처와 함께 정리 |
| 공개된 자료 받기 | 사용자 계정에서 열람할 수 있도록 공개된 모듈의 파일·페이지·링크를 확인하고 저장 |
| 새 자료와 수정본 반영하기 | 파일 ID·수정 시각·로컬 저장 기록을 비교해 필요한 자료만 추가로 저장 |
| 이번 주 할 일 확인하기 | 주요 공지, 마감 일정, 본인의 제출 상태를 연결해 필요한 행동 정리 |
| 일정이 몰리는 주 확인하기 | 과제·시험·일정과 실래버스에 명시된 날짜를 모아 비교 |

이 표는 Codex가 스킬 지침에 따라 수행하는 작업 흐름입니다. 포함된 `scripts/canvas_api.py`는 API 조회와 파일 다운로드를 담당하며, 폴더 구성·내용 읽기·표 작성·일정 비교는 Codex가 조회 결과와 로컬 파일을 이용해 수행합니다.

## 사용 환경

- Python 3.10 이상이 필요하며, 별도 Python 패키지를 설치하지 않습니다.
- 로컬 파일을 읽고 저장하며 명령을 실행하고 eTL에 네트워크 요청을 보낼 수 있는 Codex 실행환경이 필요합니다.
- 본인 계정의 eTL 개인 접근 토큰이 필요합니다. API의 결과는 해당 계정이 접근할 수 있는 과목과 자료를 기준으로 합니다.

스킬 파일을 ChatGPT 대화에 붙이거나 웹에 업로드하는 것만으로 로컬 API 실행환경이 연결되지는 않습니다. 이 폴더를 Codex가 읽을 수 있는 스킬 경로에 설치한 뒤 사용합니다.

## 설치

공유받은 이 폴더를 `~/git-repo/snu-myetl-skill`에 둡니다. 다음 명령은 해당 폴더를 사용자 스킬 경로에 연결합니다. 이미 같은 이름의 파일이나 링크가 있으면 안내만 출력하므로, 기존 설치를 덮어쓰지 않습니다.

```sh
mkdir -p "$HOME/.agents/skills"
if [ -e "$HOME/.agents/skills/snu-myetl-skill" ] || [ -L "$HOME/.agents/skills/snu-myetl-skill" ]; then
  printf '%s\n' '기존 스킬 경로가 있습니다. 기존 설치를 확인하세요.'
else
  ln -s "$HOME/git-repo/snu-myetl-skill" "$HOME/.agents/skills/snu-myetl-skill"
fi
```

설치 후 Codex에서 새 대화를 열고 `$snu-myetl-skill`을 지정해 요청합니다. 폴더를 다른 위치에 두었다면 위 명령의 링크 원본 경로를 실제 폴더 위치로 바꿉니다.

## 인증 설정

eTL에서 본인 계정의 개인 접근 토큰을 발급하고, 사용자가 로컬 환경파일에 직접 입력합니다. 토큰을 채팅에 붙여넣지 않습니다.

```sh
mkdir -p "$HOME/.config/snu-myetl-skill"
touch "$HOME/.config/snu-myetl-skill/.env"
chmod 600 "$HOME/.config/snu-myetl-skill/.env"
nano "$HOME/.config/snu-myetl-skill/.env"
```

환경파일에는 다음 형식으로 설정합니다. 예시 문구를 본인의 토큰으로 바꿉니다.

```dotenv
CANVAS_API_TOKEN=본인의_개인_접근_토큰
```

실행환경에 이미 `CANVAS_API_TOKEN`이 설정되어 있으면 사용할 수 있습니다. 기본 환경파일은 `~/.config/snu-myetl-skill/.env`이며, 다른 파일은 `--env-file`로 지정합니다. 기존 `~/.env`에서는 `CANVAS_API_TOKEN` 항목만 추가로 읽을 수 있습니다. 환경파일을 셸에서 실행하는 `source` 방식은 사용하지 않습니다.

설정 후 스킬 폴더에서 수강 과목 조회를 실행해 연결을 확인합니다.

```sh
cd "$HOME/git-repo/snu-myetl-skill"
python3 scripts/canvas_api.py courses
```

다른 환경파일을 사용하는 예시입니다.

```sh
python3 scripts/canvas_api.py --env-file "$HOME/.config/snu-myetl-skill/별도설정.env" courses
```

## 처음 요청해 보기

```text
$snu-myetl-skill
학업/2026-2 폴더에 이번 학기 수강 과목별 폴더를 만들어줘.
```

```text
각 수업의 실래버스를 찾아 해당 폴더에 저장해줘.
교수·조교 연락처, 연구실, 오피스아워, 교재, 평가 비중을
출처와 함께 한 표로 정리해 학기 폴더에 저장해줘.
```

```text
현재 공개된 모듈에서 아직 안 받은 자료를 과목별·주차별로 받아줘.
이번 학기 시험과 주요 과제 일정을 모아 일정이 몰리는 주도 알려줘.
```

```text
새로 올라오거나 수정된 자료를 반영하고,
바뀐 공지와 이번 주 미제출 과제를 알려줘.
```

기재되지 않은 연락처나 일정은 추측해서 채우지 않습니다. 확인한 항목에는 원문 출처를 붙이고, 아직 확인되지 않은 항목은 그렇게 표시합니다. 수강 목록에 여러 학기가 섞여 있으면 학기 정보와 사용자의 요청을 대조해 대상 과목을 정합니다.

## API 명령 예시

API를 직접 확인할 때는 스킬 폴더에서 다음 명령을 실행합니다. `<과목ID>`와 `<파일ID>`는 실제 조회 결과의 ID로 바꿉니다.

```sh
python3 scripts/canvas_api.py get /courses --param 'enrollment_type=student'
python3 scripts/canvas_api.py get '/courses/<과목ID>' --param 'include[]=syllabus_body'
python3 scripts/canvas_api.py download '<파일ID>' --destination '학업/2026-2/과목/자료' --course-root '학업/2026-2/과목'
```

실제 파일명·저장 위치와 조회 결과를 확인해 작업을 이어갑니다. 상세 API 설명은 [Canvas API 안내](<references/Canvas API.md>), 단계별 작업 절차는 [사용 흐름](<references/사용 흐름.md>)을 참고합니다.

`--course-root`에 같은 과목 폴더를 지정하면 모듈명이 바뀌거나 파일이 다른 주차에 다시 연결되어도 저장 기록을 재사용합니다. 수정본은 별도 이름으로 보존합니다.

## 구성

| 파일 | 역할 |
|---|---|
| `SKILL.md` | 스킬 사용 조건과 작업 지침 |
| `scripts/canvas_api.py` | Canvas API 조회와 파일 다운로드 |
| `references/Canvas API.md` | API 기능과 호출 안내 |
| `references/사용 흐름.md` | 개강 준비와 학기 중 작업 절차 |
| `agents/openai.yaml` | Codex 표시 이름과 기본 요청 문구 |

## 공유와 제출

공유할 것은 이 스킬 폴더입니다. 인증 환경파일, 개인 수강 자료, 개인 연락처, 다운로드 기록과 실제 응답을 담은 결과 폴더는 공유본에 넣지 않습니다. 시연 화면에는 자료를 공개한 범위에 맞는 내용과 가림 처리한 계정 정보를 사용합니다.

위의 요청 예시를 따라 개강 준비부터 후속 업데이트까지 이어서 사용할 수 있습니다. 시간 절감이나 성공률은 실제 비교 실행 후 기록하며, 이 문서에는 측정하지 않은 수치를 제시하지 않습니다.

## 공식 문서

- [Codex 스킬 안내](https://developers.openai.com/codex/skills/)
- [Canvas API 안내](https://developerdocs.instructure.com/services/canvas)

## 실행 도구 검증

스킬 폴더에서 다음 명령으로 외부 요청 없는 검증을 실행할 수 있습니다.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

검증은 가짜 API 응답과 임시 저장폴더를 사용합니다. 페이지네이션, 인증값이 제거된 첨부 링크, 신규 퀴즈 경로, 읽음 상태 보존, 중복 다운로드, 모듈명 변경, 수정본·로컬 수정 보존, 불완전 다운로드를 확인합니다. 실계정의 수강 과목·자료·토큰을 사용하지 않습니다. 실제 eTL을 이용한 개강 시연과 효과 측정은 별도로 진행합니다.
