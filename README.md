# ukino-dreamnote-extractor

[유키노 드림노트](http://ukino.net/) (Ukino DreamNote)의 `DATA.mdb` 파일에 저장된 모든 메모·스토리·사전을  
원래의 폴더 트리 구조 그대로 Markdown(`.md`) 파일로 추출하는 Python 스크립트입니다.

---

## 특징

- 폴더 트리 구조 완벽 보존 (프로젝트 > 폴더 > 하위 폴더 > 파일)
- 메모 (`FRM_MEMO`), 스토리 (`FRM_STORY`), 사전 (`FRM_DIC`) 추출
- 스토리의 여러 챕터(페이지)를 하나의 Markdown 파일로 합산
- RTF 본문에서 한국어 (cp949) 텍스트를 정확히 디코딩
- 파일명 중복 시 자동으로 번호 추가

---

## 요구사항

| 항목 | 버전 |
|------|------|
| Python | 3.10 이상 |
| [mdbtools](https://github.com/mdbtools/mdbtools) | 1.0 이상 |

### macOS

```bash
brew install mdbtools
```

### Linux (Debian/Ubuntu)

```bash
sudo apt install mdbtools
```

### Windows

[mdbtools for Windows](https://github.com/lsgunth/mdbtools-win) 참고 또는 WSL 사용을 권장합니다.

---

## 사용법

```bash
python3 extract.py DATA.mdb [출력_디렉터리] [옵션]
```

| 인수 / 옵션 | 설명 |
|-------------|------|
| `DATA.mdb` | Ukino DreamNote 데이터 파일 경로 (필수) |
| `출력_디렉터리` | 추출 결과를 저장할 폴더 (기본값: `output`) |
| `--merge-pages` | 여러 페이지를 하나의 .md 파일로 합산 (기본: 페이지별 파일 분리) |

### 예시

```bash
# 기본 실행 (페이지별 파일 분리)
python3 extract.py "C:\Program Files (x86)\Ukino DreamNote CS\My\DATA.mdb"

# 출력 폴더 지정
python3 extract.py DATA.mdb ~/Documents/extracted_notes

# 페이지를 하나의 파일로 합산
python3 extract.py DATA.mdb output --merge-pages
```

### 출력 구조 예시

**기본 (페이지 분리)** — 날짜·챕터 등 페이지가 각각 별도 파일로 생성됩니다.

```
output/
└── 내 프로젝트/
    ├── 일기장/
    │   └── 공중보건의사/
    │       ├── 2017.04.18.화.md
    │       ├── 2017.04.19.수.md
    │       └── ...
    └── 소설/
        └── 1장/
            ├── 프롤로그.md
            ├── 챕터1.md
            └── 챕터2.md
```

**`--merge-pages`** — 모든 페이지가 하나의 파일로 합산됩니다.

```
output/
└── 내 프로젝트/
    ├── 일기장/
    │   ├── 공중보건의사.md   ← 모든 날짜가 ## 제목 으로 구분
    │   └── 육군훈련소.md
    └── 소설/
        └── 1장.md            ← 프롤로그·챕터1·챕터2가 한 파일
```

---

## DATA.mdb 파일 위치

Ukino DreamNote CS는 설치 폴더 내 `My` 하위 폴더에 `DATA.mdb`를 저장합니다.  
Windows 기본 경로는 아래 두 가지 중 하나입니다.

```
C:\Program Files\Ukino DreamNote CS\My\DATA.mdb
C:\Program Files (x86)\Ukino DreamNote CS\My\DATA.mdb
```

> 64비트 Windows에서는 32비트 프로그램이 `Program Files (x86)`에 설치되는 경우가 많습니다.  
> 위 두 경로 중 실제로 존재하는 쪽을 사용하세요.

---

## 제한사항

- 캐릭터 시트 (`FRM_CHARACTER`), 연표 (`FRM_CHRO`), 도트 그림판 (`FRM_DOTT`) 등의 특수 폼은 추출하지 않습니다.
- RTF 서식(굵게, 기울임, 색상 등)은 Markdown으로 변환되지 않으며 평문으로만 추출됩니다.
- 이미지는 추출되지 않습니다.

---

## 라이선스

MIT
