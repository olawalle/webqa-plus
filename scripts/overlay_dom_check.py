import asyncio
from playwright.async_api import async_playwright
from webqa_plus.core.visual_overlay import VisualOverlay


async def main() -> None:
    overlay = VisualOverlay(
        {
            "overlay_position": "bottom-right",
            "overlay_opacity": 0.9,
            "update_interval_ms": 100,
        }
    )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://example.com")

        await overlay.inject(page)
        await overlay.update(
            page,
            flow_name="Primary Objective Flow",
            current_phase="testing",
            objective_text="Complete the primary user objective and verify successful persistence.",
            current_step=1,
            max_steps=5,
            completed_flows=[],
            upcoming_flows=["Primary Objective Flow"],
            url_count=1,
            coverage=20.0,
            current_action="click primary call-to-action",
        )

        has_input = await page.locator("#webqa-plus-directive-input").count()
        phase = await page.locator("#current-phase").inner_text()
        flow_text = await page.locator("#current-flow").inner_text()
        progress_text = await page.locator("#progress-text").inner_text()

        print(f"has_input={has_input}")
        print(f"phase={phase}")
        print(f"flow_text={flow_text}")
        print(f"progress_text={progress_text}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
