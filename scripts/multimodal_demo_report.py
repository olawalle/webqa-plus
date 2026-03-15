from pathlib import Path
import asyncio
from PIL import Image, ImageDraw

from webqa_plus.reporter.pdf_generator import PDFReportGenerator
from webqa_plus.utils.config import AppConfig


def make_images(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, color in [
        ("step_0001_before_full.png", (200, 220, 255)),
        ("step_0001_before_crop.png", (180, 200, 240)),
        ("step_0001_after_full.png", (210, 255, 210)),
        ("step_0001_after_crop.png", (180, 240, 180)),
        ("step_0001_annotated_failure.png", (255, 220, 220)),
    ]:
        image = Image.new("RGB", (640, 360), color=color)
        draw = ImageDraw.Draw(image)
        draw.text((20, 20), name, fill=(0, 0, 0))
        image.save(out / name)


async def main() -> None:
    cfg = AppConfig()
    reporter = PDFReportGenerator(cfg)

    artifacts_dir = Path("reports/visual_artifacts")
    make_images(artifacts_dir)

    state = {
        "visited_urls": ["https://example.com"],
        "llm_calls": 1,
        "estimated_cost": 0.001,
        "test_results": [
            {
                "step_number": 1,
                "agent": "tester",
                "action": "click",
                "target": "#submit",
                "status": "failed",
                "error_message": "Missing confirmation banner",
            }
        ],
        "discovered_flows": [],
        "errors": ["Missing confirmation banner"],
        "artifacts": {
            "step_visuals": {
                "1": {
                    "before_full": str(artifacts_dir / "step_0001_before_full.png"),
                    "before_crop": str(artifacts_dir / "step_0001_before_crop.png"),
                    "after_full": str(artifacts_dir / "step_0001_after_full.png"),
                    "after_crop": str(artifacts_dir / "step_0001_after_crop.png"),
                    "annotated_failure": str(artifacts_dir / "step_0001_annotated_failure.png"),
                    "ocr": {
                        "matched_expected": False,
                        "confidence": "medium",
                        "summary": "OCR found no success message",
                        "evidence_keywords": ["error", "required"],
                    },
                }
            }
        },
    }

    await reporter.generate(
        {"state": state, "config": cfg.model_dump(), "duration": 3.2},
        Path("reports/report_multimodal_demo.pdf"),
    )
    print("generated reports/report_multimodal_demo.html")


if __name__ == "__main__":
    asyncio.run(main())
