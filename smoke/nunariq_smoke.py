import asyncio
import json

from app.schemas.discovery import DiscoveryRequest, ICPFilters, SellerInput
from app.services.discovery_amplemarket import run_discovery
from app.services.icp_preview import generate_icp_preview

SELLER = SellerInput(
    website="https://nunariq.com",
    company_name="NunarIQ",
    deck_text=(
        "Nunar CustomsIQ - Dubai Customs Paperwork, Done. In Minutes. AI-powered operations intelligence for freight forwarders. "
        "Reads commercial invoices, packing lists, bills of lading and other customs documents from PDF/image/email; extracts 40+ fields; "
        "validates against UAE customs rules and business logic; auto-submits to Dubai Trade Portal via RPA; human-in-the-loop review for exceptions. "
        "Problems: manual re-keying, 8+ documents per shipment, data-entry errors causing holds/fines/client dissatisfaction, staff time spent on data entry. "
        "Inputs can arrive via email, browser upload, WhatsApp/shared folder."
    ),
    product_hint="customs clearance automation for UAE freight forwarders and customs operations",
)


async def main():
    preview = await generate_icp_preview(SELLER)
    print("SMOKE ICP_PREVIEW " + json.dumps(preview.model_dump(mode="json"), ensure_ascii=True), flush=True)

    req = DiscoveryRequest(
        seller=SELLER,
        icp=ICPFilters(
            countries=preview.recommended_countries,
            industries=preview.recommended_industries,
            target_functions=preview.recommended_functions,
            target_titles=preview.recommended_titles,
            headcount_min=preview.headcount_min,
            headcount_max=preview.headcount_max,
            account_limit=preview.account_limit,
            signal_window_days=preview.signal_window_days,
        ),
    )

    def progress(stage: str):
        print("SMOKE STAGE " + stage, flush=True)

    result = await run_discovery(req, progress=progress)
    payload = result.model_dump(mode="json")
    print("SMOKE RESULT " + json.dumps({
        "candidate_count": payload.get("candidate_count"),
        "researched_count": payload.get("researched_count"),
        "accounts": [
            {
                "company_name": a.get("company_name"),
                "score": a.get("score"),
                "tier": a.get("tier"),
                "why_now": a.get("why_now"),
                "product_fit": a.get("product_fit"),
            }
            for a in payload.get("accounts", [])
        ],
    }, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
