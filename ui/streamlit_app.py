"""Streamlit Approvals Inbox and Audit UI for lease-event-agent.

Interacts with the FastAPI backend (API_URL) providing:
  1. Monitored lease events inbox with urgency and confidence badges.
  2. Cited memo review with side-by-side document chunk text and highlighted citations.
  3. Red quarantine alert banner for detected prompt injection attempts.
  4. Human-in-the-loop decision controls (Approve, Reject, Request Revision).
  5. Cryptographic audit trail inspector with one-click chain verification and JSON export.
  6. Demo injection simulator in sidebar.
"""

import os
import json
import requests
import streamlit as st
from datetime import datetime

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")

st.set_page_config(
    page_title="Lease Event Approvals Inbox",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for polished commercial real estate styling
st.markdown(
    """
    <style>
    .main { background-color: #F8FAFC; }
    .stCard {
        background-color: white;
        padding: 18px;
        border-radius: 8px;
        border: 1px solid #E2E8F0;
        margin-bottom: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    .badge-high {
        background-color: #FED7D7;
        color: #9B2C2C;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: 600;
        font-size: 11px;
    }
    .badge-medium {
        background-color: #FEEBC8;
        color: #7B341E;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: 600;
        font-size: 11px;
    }
    .badge-low {
        background-color: #E2E8F0;
        color: #2D3748;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: 600;
        font-size: 11px;
    }
    .badge-warn {
        background-color: #FFF5F5;
        color: #C53030;
        border: 1px solid #FEB2B2;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: 600;
        font-size: 11px;
    }
    .badge-demo {
        background-color: #EBF8FF;
        color: #2B6CB0;
        border: 1px solid #BEE3F8;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: 700;
        font-size: 11px;
    }
    .quarantine-banner {
        background-color: #FFF5F5;
        border-left: 5px solid #E53E3E;
        padding: 14px;
        border-radius: 6px;
        margin-bottom: 18px;
        color: #9B2C2C;
    }
    .cited-box {
        background-color: #F7FAFC;
        border-left: 3px solid #3182CE;
        padding: 10px;
        margin: 6px 0;
        font-size: 13px;
    }
    .highlighted-chunk {
        background-color: #FEFCBF;
        padding: 2px 4px;
        border-radius: 2px;
        font-weight: 500;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def api_get(endpoint: str):
    """Safe GET helper against FastAPI."""
    try:
        r = requests.get(f"{API_URL}{endpoint}", timeout=10)
        return r
    except requests.exceptions.RequestException as e:
        st.error(f"Failed to connect to backend at {API_URL}: {e}")
        return None


def api_post(endpoint: str, json_data: dict = None):
    """Safe POST helper against FastAPI."""
    try:
        r = requests.post(f"{API_URL}{endpoint}", json=json_data or {}, timeout=15)
        return r
    except requests.exceptions.RequestException as e:
        st.error(f"Failed to connect to backend at {API_URL}: {e}")
        return None


# ================= SIDEBAR =================
with st.sidebar:
    st.title("🏢 Lease Event Agent")
    st.caption("Human-in-the-Loop Asset Management")

    # Backend Connection Status
    health_res = api_get("/health")
    if health_res and health_res.status_code == 200:
        h_data = health_res.json()
        st.success(f"Backend Online ({h_data['llm_mode'].upper()} mode)")
    else:
        st.error("Backend Offline (Check FastAPI server)")

    st.divider()

    st.subheader("⚡ Agent Controls")
    if st.button("🚀 Run Agent Now", use_container_width=True, type="primary"):
        with st.spinner("Executing agent across in-window leases..."):
            res = api_post("/agent/runs")
            if res and res.status_code in [200, 201]:
                st.success(f"Agent executed: {res.json().get('triggered')} leases processed.")
                st.rerun()

    if st.button("🛡️ Run Injection Demo", use_container_width=True):
        with st.spinner("Generating adversarial injection lease and analyzing..."):
            demo_res = api_post("/demo/injection")
            if demo_res and demo_res.status_code == 200:
                d = demo_res.json()
                st.warning(f"Adversarial attack quarantined! Run: {d['run_id'][:8]}...")
                st.session_state["selected_run_id"] = d["run_id"]
                st.rerun()

    st.divider()
    st.info(
        "**System Architecture:**\n"
        "• LangGraph StateGraph\n"
        "• SHA-256 Hash Chained Audit\n"
        "• Regex & Homoglyph Injection Guard\n"
        "• Cross-Register Pydantic v2 Validator"
    )


# ================= MAIN TABS =================
tab_inbox, tab_audit = st.tabs(["📥 Approvals Inbox", "📜 Cryptographic Audit Trail"])

# ----------------- TAB 1: INBOX & MEMO DETAIL -----------------
with tab_inbox:
    inbox_res = api_get("/inbox?status_filter=pending_approval")
    items = inbox_res.json() if inbox_res and inbox_res.status_code == 200 else []

    col_list, col_detail = st.columns([1, 2])

    with col_list:
        st.subheader(f"Pending Reviews ({len(items)})")

        if not items:
            st.info("Inbox is clear! No memos currently pending human sign-off.")
            st.caption("Use 'Run Agent Now' or 'Run Injection Demo' in the sidebar to populate items.")
        else:
            for item in items:
                run_id = item["run_id"]
                is_selected = st.session_state.get("selected_run_id") == run_id

                urgency_class = (
                    "badge-high" if item["urgency"] == "HIGH"
                    else "badge-medium" if item["urgency"] == "MEDIUM"
                    else "badge-low"
                )

                card_box = st.container()
                with card_box:
                    st.markdown(
                        f"""
                        <div class="stCard">
                            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                                <div>
                                    <span class="{urgency_class}">{item['urgency']} URGENCY</span>
                                    {f'<span class="badge-demo" style="margin-left:4px;">DEMO</span>' if item.get('is_demo') else ''}
                                </div>
                                <span style="font-size:12px; color:#718096;">{item['days_to_event']} days remaining</span>
                            </div>
                            <h4 style="margin:2px 0 6px 0; color:#1A202C;">{item['tenant']}</h4>
                            <div style="font-size:12px; color:#4A5568; margin-bottom:4px;">
                                📍 <b>{item['asset_name']}</b> • 🏷️ {item['event_type']}
                            </div>
                            <div style="font-size:12px; color:#718096;">
                                Rent: £{item['passing_rent']['amount']:,.2f} • Conf: {int(item['confidence']*100)}%
                                {f'<span class="badge-warn">⚠️ LOW CONF</span>' if item.get('low_confidence') else ''}
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    if st.button("Review Memo ➔", key=f"sel_{run_id}", use_container_width=True):
                        st.session_state["selected_run_id"] = run_id
                        st.rerun()

    # Detail View on Right
    with col_detail:
        selected_run_id = st.session_state.get("selected_run_id")
        if not selected_run_id and items:
            selected_run_id = items[0]["run_id"]

        if not selected_run_id:
            st.write("Select a lease event memo from the list on the left to inspect details.")
        else:
            detail_res = api_get(f"/inbox/{selected_run_id}")
            if not detail_res or detail_res.status_code != 200:
                st.error("Could not load details for selected run.")
            else:
                detail = detail_res.json()
                memo = detail.get("memo", {})
                quarantined = detail.get("quarantined_chunks", [])
                cited_chunks = detail.get("cited_chunks", [])
                warnings = detail.get("validation_warnings", [])

                # QUARANTINE RED BANNER
                if quarantined:
                    st.markdown(
                        f"""
                        <div class="quarantine-banner">
                            <h4 style="margin:0 0 6px 0;">🛡️ PROMPT INJECTION ATTEMPT DETECTED & QUARANTINED</h4>
                            <b>{len(quarantined)} chunk(s)</b> were isolated from the document context prior to LLM inference.
                            The malicious directives were stripped to prevent unauthorized instruction override.
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    with st.expander("🔍 View Quarantined Chunk Details & Injection Reasons"):
                        for q in quarantined:
                            st.markdown(f"**Chunk ID:** `{q['chunk_id']}` (Page {q['page']}) | **Threat Score:** {q['score']:.2f}")
                            st.write(f"**Triggered Indicators:** {', '.join(q['reasons'])}")
                            st.code(q["text"], language="text")

                # Validation Warnings Notice
                if warnings:
                    st.warning(f"**Validation Notices:** {', '.join(warnings)}")

                # Memo Header
                st.subheader(f"Notification Memo: {memo.get('tenant_name', {}).get('value')} ({memo.get('event_type')})")
                st.caption(f"Run ID: `{selected_run_id}` • Asset: {detail.get('asset_name')} ({detail.get('asset_id')})")

                # Two-column layout for Memo Summary and Source Documents
                left_memo, right_source = st.columns([1, 1])

                with left_memo:
                    st.markdown("#### 📋 Executive Summary")
                    st.info(memo.get("executive_summary"))

                    st.markdown("#### 🔍 Cited Key Figures & Covenants")
                    figures_data = [
                        ("Tenant Legal Name", memo.get("tenant_name", {})),
                        ("Annual Passing Rent", memo.get("passing_rent", {})),
                        ("Event Target Date", memo.get("event_date", {})),
                        ("Passing Rent at Risk", memo.get("rent_at_risk", {})),
                        ("Reinstatement Covenant", memo.get("reinstatement", {})),
                    ]
                    for label, cited_obj in figures_data:
                        val = cited_obj.get("value") or cited_obj.get("amount") or cited_obj.get("date")
                        if isinstance(val, float):
                            val_str = f"£{val:,.2f}"
                        else:
                            val_str = str(val)

                        st.markdown(
                            f"""
                            <div class="cited-box">
                                <b>{label}:</b> {val_str}<br/>
                                <span style="font-size:11px; color:#718096;">
                                    Source: <code>{cited_obj.get('source_chunk_id')}</code> (Page {cited_obj.get('page')})
                                </span>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                    # Break conditions
                    break_conds = memo.get("break_conditions", [])
                    if break_conds:
                        st.markdown("<b>Break Pre-Conditions:</b>", unsafe_allow_html=True)
                        for bc in break_conds:
                            st.markdown(
                                f"• {bc.get('value')} *(Source: `{bc.get('source_chunk_id')}`, Page {bc.get('page')})*"
                            )

                    st.markdown("#### 🎯 Recommended Commercial Actions")
                    for act in memo.get("recommended_actions", []):
                        st.markdown(f"✅ {act}")

                with right_source:
                    st.markdown("#### 📄 Ground-Truth Source Document Chunks")
                    st.caption("Verified text extracted from registered synthetic lease PDF:")

                    if not cited_chunks:
                        st.write("No cited chunks available.")
                    else:
                        for chunk in cited_chunks:
                            with st.expander(f"📌 Chunk `{chunk['chunk_id']}` (Page {chunk['page']})", expanded=True):
                                st.markdown(
                                    f"<div style='font-family:monospace; font-size:12px; white-space:pre-wrap; background:#F8FAFC; padding:8px; border-radius:4px;'>{chunk['text']}</div>",
                                    unsafe_allow_html=True,
                                )

                # DECISION BAR
                st.divider()
                st.markdown("### ✍️ Asset Manager Decision & Routing")

                c_appr, c_comm = st.columns([1, 2])
                with c_appr:
                    approver_id = st.text_input("Reviewer / Approver ID", value="asset.manager@example.com")
                with c_comm:
                    decision_comment = st.text_input("Decision Comment / Revision Feedback (Required for Reject & Revise)")

                col_btn1, col_btn2, col_btn3 = st.columns(3)

                with col_btn1:
                    if st.button("✅ Approve Memo", use_container_width=True, type="primary"):
                        res = api_post(
                            f"/inbox/{selected_run_id}/approve",
                            {"approver_id": approver_id, "comment": decision_comment},
                        )
                        if res and res.status_code == 200:
                            st.success("Memo successfully approved and archived!")
                            st.session_state["selected_run_id"] = None
                            st.rerun()
                        elif res:
                            st.error(f"Error {res.status_code}: {res.json().get('detail')}")

                with col_btn2:
                    if st.button("❌ Reject Memo", use_container_width=True):
                        if not decision_comment.strip():
                            st.error("Rejection comment is mandatory!")
                        else:
                            res = api_post(
                                f"/inbox/{selected_run_id}/reject",
                                {"approver_id": approver_id, "comment": decision_comment},
                            )
                            if res and res.status_code == 200:
                                st.warning("Memo rejected and audit trail recorded.")
                                st.session_state["selected_run_id"] = None
                                st.rerun()
                            elif res:
                                st.error(f"Error {res.status_code}: {res.json().get('detail')}")

                with col_btn3:
                    if st.button("🔄 Request Revision", use_container_width=True):
                        if not decision_comment.strip():
                            st.error("Revision feedback instructions are mandatory!")
                        else:
                            with st.spinner("Re-queuing agent with feedback..."):
                                res = api_post(
                                    f"/inbox/{selected_run_id}/revise",
                                    {"approver_id": approver_id, "comment": decision_comment},
                                )
                                if res and res.status_code == 200:
                                    d = res.json()
                                    st.info(f"Re-queued agent! New Run ID: `{d['new_run_id'][:8]}...`")
                                    st.session_state["selected_run_id"] = d["new_run_id"]
                                    st.rerun()
                                elif res:
                                    st.error(f"Error {res.status_code}: {res.json().get('detail')}")


# ----------------- TAB 2: AUDIT TRAIL -----------------
with tab_audit:
    st.subheader("📜 Cryptographic Tamper-Evident Audit Ledger")
    st.caption("Every state transition is signed with SHA-256 hash chaining under SQLite append-only triggers.")

    col_btn_verify, col_btn_download, _ = st.columns([1, 1, 2])

    with col_btn_verify:
        if st.button("🔒 Verify Chain Integrity", use_container_width=True):
            exp_res = api_get("/audit/export")
            if exp_res and exp_res.status_code == 200:
                v = exp_res.json()["chain_verification"]
                if v["valid"]:
                    st.success(f"✅ Cryptographic Chain VALID: {v['checked']} entries verified without tampering.")
                else:
                    st.error(f"❌ TAMPER DETECTED: Chain broken at `{v['first_bad_entry']}`. Reason: {v['reason']}")

    audit_export_res = api_get("/audit/export")
    if audit_export_res and audit_export_res.status_code == 200:
        export_payload = audit_export_res.json()
        trail = export_payload.get("trail", [])

        with col_btn_download:
            st.download_button(
                label="📥 Download Audit Ledger (JSON)",
                data=json.dumps(export_payload, indent=2),
                file_name=f"audit_log_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                use_container_width=True,
            )

        st.markdown(f"**Total Cryptographic Entries:** `{len(trail)}`")

        # Table display
        table_rows = []
        for e in trail:
            table_rows.append({
                "Seq": e.get("seq_id"),
                "Event Type": e.get("event_type"),
                "Timestamp (UTC)": e.get("timestamp"),
                "Run ID": e.get("run_id")[:8] + "...",
                "Entry Hash": e.get("entry_hash")[:16] + "...",
                "Prev Hash": e.get("prev_hash")[:16] + "...",
                "User/Agent": e.get("user_id") or e.get("agent_id"),
                "Decision": e.get("decision") or "-",
            })

        st.dataframe(table_rows, use_container_width=True, hide_index=True)

        with st.expander("🔍 Inspect Specific Run Trail"):
            target_run = st.text_input("Enter Run ID to inspect:")
            if target_run:
                run_trail_res = api_get(f"/audit/{target_run.strip()}")
                if run_trail_res and run_trail_res.status_code == 200:
                    st.json(run_trail_res.json())
                else:
                    st.warning("No audit entries found for that Run ID.")
