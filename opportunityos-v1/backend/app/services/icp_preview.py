import asyncio

from app.schemas.discovery import ICPPreview, SellerInput
from app.services.discovery import _openai_json
from app.services.research import research_company


async def generate_icp_preview(seller: SellerInput) -> ICPPreview:
    docs = await research_company(str(seller.website))
    return await asyncio.to_thread(
        _openai_json,
        "icp_preview",
        ICPPreview,
        {
            "task": (
                "Create an evidence-informed ICP preview for this B2B seller using the website research and product deck. "
                "The customer should not need to configure ICP filters manually. Infer 2-4 practical ICP segments, prioritizing markets where the product has a clear operational or economic reason to buy. "
                "Recommend countries, industries, company-size range, buyer functions, buyer titles, and public buying triggers that can be used by downstream account discovery. "
                "Use broad enough filters to discover opportunities but avoid generic everything-for-everyone ICPs. "
                "Default account_limit to 10 and signal_window_days to 90 unless the product clearly requires otherwise. "
                "Confidence should reflect how clearly the website and deck support the inferred ICP."
            ),
            "seller": seller.model_dump(mode="json"),
            "website_research": docs[:16],
        },
    )
