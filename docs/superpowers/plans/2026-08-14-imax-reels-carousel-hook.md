# Prickly IMAX Reel and Carousel Copy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a publication-ready Korean copy package for one 25–30 second Reel and one nine-slide carousel that turns current audience frustration about Yongsan IMAX sellouts and resale prices into a credible Prickly IMAX Helper value proposition.

**Architecture:** Keep editorial assets separate by responsibility: the main scripts define the narrative, a variation pack supports publishing tests and DM conversion, and a claim-safety checklist records the final audit. The copy demonstrates the product through its local workflow and safeguards without the removed generic Prickly AI brand slogan.

**Tech Stack:** Korean Markdown copy assets, repository design spec, `rg`-based copy QA, Git.

## Global Constraints

- Primary hook: `용아맥 한 자리 보는데 30만 원?` followed by `그래서 누구나 자기 컴퓨터로 정가 취소표를 기다릴 수 있게 만들었다.`
- Core value: `하루 종일 새로고침하지 않아도, 내 조건에 맞는 취소표를 내 컴퓨터가 대신 기다려준다.`
- CTA: `댓글에 “아이맥스”라고 남기면 설치 방법을 보내줄게.`
- Narrative order: resale-price anger → empathy with sold-out fatigue → practical local alternative → brief workflow → safeguards → CTA.
- Reel duration target: 25–30 seconds.
- Carousel length: exactly nine slides.
- Do not use the removed line `Prickly AI는 사람이 반복하던 일을 실제로 작동하는 자동화로 바꾼다.`
- Do not promise ticket success, claim that the helper beats scalpers, imply CGV endorsement, or fabricate a booking result.
- State or preserve the operating boundary: the user's computer, the user's CGV login, the user's registered IMAX vouchers, no card-payment automation, and safety stops when requirements are not proven.
- Treat `30만 원` as a reported extreme resale example from supplied public sentiment, not a universal market price.
- Keep the voice direct, useful, slightly indignant, and non-self-congratulatory.

---

### Task 1: Main Reel and Carousel Narrative

**Files:**
- Create: `generated_assets/prickly_imax_helper_launch/copy/reel-script.md`
- Create: `generated_assets/prickly_imax_helper_launch/copy/carousel-copy.md`
- Reference: `docs/superpowers/specs/2026-08-14-imax-reels-carousel-hook-design.md`

**Interfaces:**
- Consumes: approved hook, value proposition, CTA, product workflow, and claim boundaries from the design spec.
- Produces: one timed Reel script and one numbered nine-slide carousel used by Tasks 2 and 3.

- [ ] **Step 1: Create the Reel script with seven timed beats**

Write `reel-script.md` with these exact sections and durations:

```markdown
# Reel Script

## 0–3초 — 후킹
화면 문구:
내레이션:
화면/편집:

## 3–7초 — 문제
...

## 7–11초 — 해결책 공개
...

## 11–18초 — 사용 흐름
...

## 18–23초 — 감시 결과
...

## 23–27초 — 안전장치
...

## 27–30초 — CTA
...
```

Keep spoken narration short enough for approximately 30 seconds, and show setup and monitoring as real product UI directions rather than abstract brand claims.

- [ ] **Step 2: Check Reel duration and forbidden claims**

Run:

```bash
rg -n "보장|무조건|암표상보다|CGV.{0,8}(승인|공식)|예매 성공했습니다|Prickly AI는 사람이 반복하던 일을" generated_assets/prickly_imax_helper_launch/copy/reel-script.md
```

Expected: no matches. Manually read the narration aloud once; expected reading time is 25–30 seconds at a clear social-video pace.

- [ ] **Step 3: Create the nine-slide carousel copy**

Write `carousel-copy.md` using this exact slide sequence:

```markdown
# Carousel Copy

## 1/9 — 암표 가격 후킹
헤드라인:
본문:
비주얼 방향:

## 2/9 — 매진과 대기열
...

## 3/9 — 새로고침 피로와 포기
...

## 4/9 — 로컬 감시 대안
...

## 5/9 — 직접 로그인과 조건 설정
...

## 6/9 — 새 날짜와 연속 좌석 감시
...

## 7/9 — 안전장치
...

## 8/9 — 가치 제안
...

## 9/9 — 댓글 CTA
...
```

Slide 8 must use `암표를 사는 대신, 정가 취소표를 기다릴 수 있는 선택지.` The slide 1 body must frame 300,000 won as an observed resale example, not a normal price.

- [ ] **Step 4: Verify slide count and mandatory lines**

Run:

```bash
test "$(rg -c '^## [1-9]/9' generated_assets/prickly_imax_helper_launch/copy/carousel-copy.md)" -eq 9
rg -F '암표를 사는 대신, 정가 취소표를 기다릴 수 있는 선택지.' generated_assets/prickly_imax_helper_launch/copy/carousel-copy.md
rg -F '댓글에 “아이맥스”라고 남기면 설치 방법을 보내줄게.' generated_assets/prickly_imax_helper_launch/copy/carousel-copy.md
```

Expected: exit 0 and both mandatory lines printed.

- [ ] **Step 5: Commit the main narrative**

```bash
git add generated_assets/prickly_imax_helper_launch/copy/reel-script.md generated_assets/prickly_imax_helper_launch/copy/carousel-copy.md
git commit -m "content: draft IMAX reel and carousel"
```

### Task 2: Hook, Caption, and DM Conversion Pack

**Files:**
- Create: `generated_assets/prickly_imax_helper_launch/copy/hook-caption-cta-pack.md`
- Consume: `generated_assets/prickly_imax_helper_launch/copy/reel-script.md`
- Consume: `generated_assets/prickly_imax_helper_launch/copy/carousel-copy.md`

**Interfaces:**
- Consumes: the approved main narrative from Task 1.
- Produces: five hook variants, one Reel caption, one carousel caption, one pinned comment, and one comment-to-DM response.

- [ ] **Step 1: Write five distinct hook variants**

Create a `후킹 A/B 테스트` section with exactly five numbered hooks. Include the approved 300,000-won hook as A, then vary the psychological entry point across sold-out fatigue, endless refreshing, giving up on IMAX, and a local-computer alternative. Do not make two variants simple synonym swaps.

- [ ] **Step 2: Write publishing and DM copy**

Add these exact sections:

```markdown
## 릴스 캡션
## 캐러셀 캡션
## 고정 댓글
## 댓글 답장
## DM 안내
```

The DM copy must distinguish installation instructions from a ticket guarantee and must remind the recipient that setup uses their own computer and CGV account.

- [ ] **Step 3: Validate package structure and removed slogan**

Run:

```bash
test "$(rg -c '^### [A-E]\.' generated_assets/prickly_imax_helper_launch/copy/hook-caption-cta-pack.md)" -eq 5
for heading in '## 릴스 캡션' '## 캐러셀 캡션' '## 고정 댓글' '## 댓글 답장' '## DM 안내'; do rg -F "$heading" generated_assets/prickly_imax_helper_launch/copy/hook-caption-cta-pack.md >/dev/null; done
! rg -F 'Prickly AI는 사람이 반복하던 일을' generated_assets/prickly_imax_helper_launch/copy/hook-caption-cta-pack.md
```

Expected: exit 0.

- [ ] **Step 4: Commit the conversion pack**

```bash
git add generated_assets/prickly_imax_helper_launch/copy/hook-caption-cta-pack.md
git commit -m "content: add IMAX hook and CTA pack"
```

### Task 3: Claim, Privacy, and Brand QA

**Files:**
- Create: `generated_assets/prickly_imax_helper_launch/copy/claim-safety-checklist.md`
- Review: `generated_assets/prickly_imax_helper_launch/copy/reel-script.md`
- Review: `generated_assets/prickly_imax_helper_launch/copy/carousel-copy.md`
- Review: `generated_assets/prickly_imax_helper_launch/copy/hook-caption-cta-pack.md`

**Interfaces:**
- Consumes: all copy deliverables from Tasks 1 and 2.
- Produces: a recorded pass/fail audit and corrected publication-ready copy.

- [ ] **Step 1: Record the claim audit**

Write a checklist containing explicit PASS/FAIL results for:

```markdown
- [ ] 30만 원은 일부 재판매 사례로 한정됨
- [ ] 예매 성공을 보장하지 않음
- [ ] CGV 공식·제휴·승인을 암시하지 않음
- [ ] 암표상보다 빠르거나 반드시 이긴다고 주장하지 않음
- [ ] 가짜 예매 완료 화면이나 모바일티켓을 요구하지 않음
- [ ] 사용자 본인 컴퓨터·계정·등록 관람권 경계가 드러남
- [ ] 카드 결제 자동화를 약속하지 않음
- [ ] 개인정보가 외부로 전송된다고 오해할 문구가 없음
- [ ] 삭제 요청 문구가 재등장하지 않음
- [ ] 계정 컨셉을 설명문 대신 제품 장면과 결과로 보여줌
```

Mark every item only after comparing all three copy files.

- [ ] **Step 2: Run a mechanical forbidden-claim scan**

Run:

```bash
rg -n "무조건|100%|보장|CGV 공식|CGV 승인|암표상.*이긴|카드.{0,6}(자동|결제)|Prickly AI는 사람이 반복하던 일을" generated_assets/prickly_imax_helper_launch/copy/*.md
```

Expected: no problematic publication-copy matches. If the checklist quotes a forbidden phrase for auditing, label it clearly as a banned example.

- [ ] **Step 3: Run mobile-readability and consistency review**

Read every headline at phone-thumbnail size and shorten any cover or slide headline that needs more than three short lines. Confirm the same product nouns are used consistently: `Prickly IMAX Helper`, `전용 Chrome`, `정가 취소표`, `IMAX 영화관람권`, and `내 컴퓨터`.

- [ ] **Step 4: Run final repository checks**

Run:

```bash
git diff --check
test "$(rg -c '^## [1-9]/9' generated_assets/prickly_imax_helper_launch/copy/carousel-copy.md)" -eq 9
test "$(rg -c '^### [A-E]\.' generated_assets/prickly_imax_helper_launch/copy/hook-caption-cta-pack.md)" -eq 5
```

Expected: exit 0.

- [ ] **Step 5: Commit the audited copy package**

```bash
git add generated_assets/prickly_imax_helper_launch/copy
git commit -m "content: audit IMAX launch copy"
```

## Self-Review Result

- Spec coverage: all Reel beats, all nine carousel slides, five hook variants, captions, pinned comment, DM copy, and claim/privacy checks are assigned to explicit tasks.
- Placeholder scan: no TBD, TODO, vague implementation instruction, or deferred validation remains.
- Interface consistency: Task 2 consumes Task 1 copy; Task 3 audits all three named artifacts and does not introduce a competing narrative.
