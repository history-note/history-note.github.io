#!/usr/bin/env python3
"""한국사 공부 노트 — 라이브(https://history-note.github.io/) 390×844 실서버 검증"""
import asyncio, pathlib, time, sys
from playwright.async_api import async_playwright

URL = "https://history-note.github.io/"
CHROME = "/workspace/.cache/ms-playwright/chromium-1255/chrome-linux64/chrome"
SHOTS = pathlib.Path("/workspace/work/history-publish/screenshots")

results, errors = [], []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("  ✅ " if ok else "  ❌ ") + name + ((" — " + str(detail)) if detail else ""))


OVERFLOW_JS = """()=>{
  const de=document.documentElement;
  const bad=[...document.querySelectorAll('.view.on *')].filter(el=>{
    if(el.closest('.jump')) return false;
    const r=el.getBoundingClientRect();
    return r.width>0 && (r.right>window.innerWidth+0.6 || r.left<-0.6);
  }).map(el=>el.className||el.tagName).slice(0,6);
  return {doc: de.scrollWidth, win: window.innerWidth, bad};
}"""


async def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        exe = pathlib.Path(CHROME)
        b = await p.chromium.launch(args=["--no-sandbox"], executable_path=str(exe) if exe.exists() else None)
        label = "LIVE-390x844"
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3,
                                  is_mobile=True, has_touch=True, locale="ko-KR")
        page = await ctx.new_page()
        page.on("console", lambda m: errors.append(f"console: {m.text}") if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("requestfailed", lambda r: errors.append(f"requestfailed: {r.url} {r.failure}"))
        await page.add_init_script("window.__err=[];addEventListener('error',e=>window.__err.push(String(e.message)));addEventListener('unhandledrejection',e=>window.__err.push(String(e.reason)));")

        t0 = time.time()
        resp = await page.goto(URL, wait_until="networkidle")
        load_ms = int((time.time() - t0) * 1000)
        check("HTTP 200 · 라이브 로드", resp is not None and resp.status == 200, f"{resp.status if resp else 'no response'} · {load_ms}ms")
        await page.wait_for_timeout(300)

        st = await page.evaluate("window.__his.state")
        check("첫 화면 카드 100장", st["deck"] == 100, st)
        check("시대 칩 8개", await page.locator("#eraGrid .era-chip").count() == 8)

        # 인라인 SVG 일러스트 (외부 이미지 0)
        sv = await page.evaluate("""()=>({chips:document.querySelectorAll('#eraGrid .ec-wm svg').length,
          art:document.querySelectorAll('#fArt svg').length, bad:document.querySelectorAll('#fBadge .bd-ic svg').length})""")
        check("일러스트 SVG 렌더(칩 8·배지 1·카드 1)", sv["chips"] == 8 and sv["art"] == 1 and sv["bad"] == 1, sv)

        # 시대 필터 전부
        expected = {1: 13, 2: 12, 3: 12, 4: 12, 5: 13, 6: 12, 7: 13, 8: 13}
        for eid, n in expected.items():
            await page.click(f'#eraGrid .era-chip[data-era="{eid}"]')
            await page.wait_for_timeout(60)
            s = await page.evaluate("window.__his.state")
            badge = await page.inner_text("#fBadge")
            check(f"시대 {eid} 필터 {n}장", s["deck"] == n and s["era"] == eid and badge.startswith("①②③④⑤⑥⑦⑧"[eid - 1]),
                  f"deck={s['deck']} badge={badge}")
            ov = await page.evaluate(OVERFLOW_JS)
            if ov["doc"] > ov["win"] or ov["bad"]:
                check(f"시대 {eid} 가로 넘침 없음", False, ov)
        await page.click("#allBtn")
        await page.wait_for_timeout(60)
        check("전체 보기 복귀", (await page.evaluate("window.__his.state"))["deck"] == 100)

        # 카드 뒤집기
        name = await page.inner_text("#fName")
        await page.click("#card")
        await page.wait_for_timeout(700)
        flipped = await page.evaluate("document.getElementById('card').classList.contains('flipped')")
        story = await page.inner_text("#bStory")
        check("카드 탭 → 뒤집기·스토리", flipped and len(story) > 20, story[:24])
        check("뒷면 이름 일치", await page.inner_text("#bName") == name)
        tags = await page.locator("#bTags .tag").count()
        check("키워드 태그 2~3개", 2 <= tags <= 3, tags)
        fs = await page.evaluate("""()=>{const f=document.querySelector('.face.front'),b=document.querySelector('.face.back');
          const cs=e=>getComputedStyle(e);return {fv:cs(f).visibility,fo:+cs(f).opacity,bv:cs(b).visibility,bo:+cs(b).opacity}}""")
        check("뒤집힌 뒤 앞면 숨김(iOS Safari 대비)", fs["fv"] == "hidden" and fs["fo"] < 0.02 and fs["bv"] == "visible", fs)
        await page.evaluate("window.__his.flip(false)")
        await page.wait_for_timeout(320)
        await page.evaluate("window.__his.setEra(5); window.__his.setIndex(0); window.__his.flip(false)")
        await page.wait_for_timeout(300)
        await (await page.query_selector("#card")).screenshot(path=str(SHOTS / "svg-card.png"))
        await page.screenshot(path=str(SHOTS / "live-390-svg.png"))
        check("SVG 카드 캐처 저장(svg-card.png)", (SHOTS / "svg-card.png").exists())
        await page.evaluate("window.__his.setEra(0); window.__his.setIndex(0)")
        await page.wait_for_timeout(150)
        await page.click("#card")
        await page.wait_for_timeout(700)
        await page.screenshot(path=str(SHOTS / "live-390-card-back.png"))

        # 외웠어요 + 새로고침 유지
        await page.click("#btnLearned")
        await page.wait_for_timeout(600)
        pill = await page.inner_text("#learnPill")
        check("외웠어요 → 진행률", "1" in pill, pill)
        await page.reload(wait_until="networkidle")
        await page.wait_for_timeout(300)
        s2 = await page.evaluate("window.__his.state")
        check("새로고침 후 외운 카드 유지", s2["learned"] == 1, s2)

        # 헷갈려요 → 오답노트
        await page.evaluate("window.__his.setIndex(2); window.__his.flip(true)")
        await page.wait_for_timeout(500)
        cname = await page.inner_text("#bName")
        await page.click("#btnConfused")
        await page.wait_for_timeout(500)
        await page.click("#tab-note")
        await page.wait_for_timeout(250)
        note_txt = await page.inner_text("#noteList")
        check("헷갈려요 → 오답노트 저장", cname in note_txt and (await page.inner_text("#noteCount")) == "1", cname)
        await page.screenshot(path=str(SHOTS / "live-390-note.png"))
        await page.click("#noteList .note-btns button.ok")
        await page.wait_for_timeout(250)
        check("'이제 알아요' → 해제", (await page.inner_text("#noteCount")) == "0")

        # 퀴즈 10문제 완주
        await page.click("#tab-quiz")
        await page.wait_for_timeout(200)
        await page.click("#startQuiz")
        await page.wait_for_timeout(300)
        seen = []
        for i in range(10):
            seen.append(await page.inner_text("#qText"))
            nchoice = await page.locator("#qChoices .choice").count()
            if nchoice != 4:
                check(f"퀴즈 {i+1} 보기 4개", False, nchoice)
            await page.locator("#qChoices .choice").nth(2).click()
            await page.wait_for_timeout(200)
            fb = await page.inner_text("#qFeedback")
            right = await page.locator("#qChoices .choice.right").count()
            if not fb or right != 1:
                check(f"퀴즈 {i+1} 피드백", False, fb[:30])
            await page.click("#qNext")
            await page.wait_for_timeout(160)
        check("퀴즈 10문제 완주 · 중복 없음", len(seen) == 10 and len(set(seen)) == 10, len(set(seen)))
        score_txt = await page.inner_text("#rScore")
        check("결과 점수 표시", "/ 10" in score_txt, score_txt)
        wrong_n = await page.locator("#rWrong .wrong-item").count()
        note_n = (await page.evaluate("window.__his.state"))["confused"]
        check("퀴즈 오답 → 오답노트 자동 저장", note_n == wrong_n, f"wrong={wrong_n} note={note_n}")
        await page.screenshot(path=str(SHOTS / "live-390-quiz-result.png"))

        # 연표
        await page.click("#tab-time")
        await page.wait_for_timeout(300)
        check("연표 100개", await page.locator("#tlList .tl-item").count() == 100)
        check("연표 시대 점프 8개", await page.locator("#tlJump button").count() == 8)
        await page.fill("#tlSearch", "대동여지도")
        await page.wait_for_timeout(350)
        check("연표 검색 '대동여지도' 1건", await page.locator("#tlList .tl-item").count() == 1)
        await page.fill("#tlSearch", "세종")
        await page.wait_for_timeout(350)
        check("연표 검색 '세종' → 세종대왕", "세종대왕" in await page.inner_text("#tlList"))
        await page.fill("#tlSearch", "없는키워드")
        await page.wait_for_timeout(350)
        check("검색 결과 없음 안내", await page.locator(".tl-empty").count() == 1)
        await page.fill("#tlSearch", "")
        await page.wait_for_timeout(350)
        await page.screenshot(path=str(SHOTS / "live-390-timeline.png"))
        await page.locator("#tlList .tl-item").nth(3).click()
        await page.wait_for_timeout(250)
        check("연표 항목 → 카드 이동", await page.evaluate("document.getElementById('view-card').classList.contains('on')"))

        # 화면별 가로 넘침
        for view in ["card", "quiz", "time", "note"]:
            await page.click(f"#tab-{view}")
            await page.wait_for_timeout(250)
            ov = await page.evaluate(OVERFLOW_JS)
            check(f"{view} 화면 가로 넘침 없음", ov["doc"] <= ov["win"] and not ov["bad"], ov)

        # 카드 100장 앞/뒤 레이아웃
        await page.click("#tab-card")
        await page.wait_for_timeout(200)
        problems = []
        for i in range(100):
            await page.evaluate(f"window.__his.setEra(0); window.__his.setIndex({i}); window.__his.flip(false)")
            front = await page.evaluate("""()=>{
              const f=document.querySelector('.face.front'), n=document.getElementById('fName'), q=document.querySelector('.qbox');
              const fr=f.getBoundingClientRect(), nr=n.getBoundingClientRect(), qr=q.getBoundingClientRect();
              return {fit: nr.bottom<=qr.top+2 && qr.bottom<=fr.bottom+1, nh:n.scrollWidth<=n.clientWidth+1};
            }""")
            await page.evaluate("window.__his.flip(true)")
            back = await page.evaluate("""()=>{
              const b=document.querySelector('.back-body'), inner=document.querySelector('.back-inner'), f=document.querySelector('.face.back');
              return {h: b.scrollHeight-b.clientHeight, w: inner.scrollWidth-inner.clientWidth, fw: f.scrollWidth-f.clientWidth};
            }""")
            if not front["fit"] or not front["nh"] or back["h"] > 1 or back["w"] > 1 or back["fw"] > 1:
                problems.append((i, front, back))
        check("카드 100장 앞/뒤 넘침 0", not problems, problems[:4])

        # 효과음 토글 저장 (음소거 상태 유지)
        await page.evaluate("window.__his.setIndex(0); window.__his.flip(false)")
        before = await page.get_attribute("#soundBtn", "aria-pressed")
        await page.click("#soundBtn")
        await page.wait_for_timeout(150)
        after = await page.get_attribute("#soundBtn", "aria-pressed")
        check("효과음 토글·저장", before != after and await page.evaluate("localStorage.getItem('his_sound_v1')") in ("on", "off"),
              f"{before}->{after}")
        await page.click("#soundBtn")
        await page.wait_for_timeout(120)

        # 콘솔·네트워크 에러
        js_err = await page.evaluate("window.__err")
        check("콘솔/페이지/네트워크 에러 0건", not errors and not js_err, (errors[:4] or js_err[:4]))

        # 외부 리소스 요청 0건 (인라인 SVG 만)
        ext = await page.evaluate("""()=>performance.getEntriesByType('resource')
          .map(e=>e.name).filter(u=>!u.startsWith(location.origin) && /^https?:/.test(u))""")
        check("외부 리소스 요청 0건", not ext, ext[:4])

        # 첫 화면 캡처
        await page.evaluate("localStorage.clear()")
        await page.reload(wait_until="networkidle")
        await page.wait_for_timeout(400)
        await page.screenshot(path=str(SHOTS / "live-390-home.png"))
        await ctx.close()
        await b.close()

    ok = sum(1 for _, o, _ in results if o)
    print(f"\n=== 결과: {ok}/{len(results)} 통과 · 콘솔/네트워크 에러 {len(errors)}건 ===")
    for r in results:
        if not r[1]:
            print("FAIL:", r[0], r[2])
    return 0 if ok == len(results) else 1


sys.exit(asyncio.run(main()))
