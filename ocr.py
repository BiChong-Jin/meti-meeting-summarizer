"""OCR fallback for image-only PDFs using OpenAI Vision API."""

import base64
import logging

import fitz
from langchain_openai import ChatOpenAI

log = logging.getLogger(__name__)


def extract_text_with_ocr(pdf_bytes: bytes, api_key: str, model: str = "gpt-4o-mini") -> str:
    """
    Extract text from an image-only PDF by rendering each page
    as an image and sending it to OpenAI's Vision API.

    Returns the extracted text from all pages combined.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    llm = ChatOpenAI(model=model, api_key=api_key, temperature=0, max_tokens=4096)

    all_text = []
    for i, page in enumerate(doc):
        # Render page to PNG at 200 DPI
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("png")
        b64_img = base64.b64encode(img_bytes).decode()

        log.info("OCR processing page %d/%d", i + 1, len(doc))

        response = llm.invoke([
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "この画像に含まれるすべてのテキストを、元のレイアウトをできるだけ保持して抽出してください。表がある場合はテキスト形式で再現してください。テキスト以外の説明は不要です。",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64_img}"},
                    },
                ],
            }
        ])
        all_text.append(response.content)

    return "\n\n".join(all_text)
