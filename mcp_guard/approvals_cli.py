"""CLI for managing approval requests."""

from __future__ import annotations

import json
import sys

from .approval_store import SQLiteApprovalQueue


def cmd_approvals_list(db_path: str, show_decided: bool) -> int:
    queue = SQLiteApprovalQueue(db_path=db_path)
    try:
        pending = queue.list_pending()
        if pending:
            print(f"PENDING ({len(pending)}):")
            print("-" * 70)
            for req in pending:
                age = int((__import__("time").time() - req.created_at))
                print(f"  {req.id[:8]}  {req.agent_id:12s}  ${req.amount_usd:7.2f}  {req.tool_name:20s}  ({age}s old)")
                if req.session_id:
                    print(f"           session={req.session_id}")
        else:
            print("No pending approval requests.")

        if show_decided:
            decided = queue.list_decided(limit=20)
            if decided:
                print()
                print(f"DECIDED (last 20):")
                print("-" * 70)
                for req in decided:
                    print(f"  {req.id[:8]}  {req.status.value:10s}  {req.agent_id:12s}  ${req.amount_usd:7.2f}  {req.tool_name}")
    finally:
        queue.close()
    return 0


def cmd_approvals_approve(db_path: str, req_id: str, decided_by: str) -> int:
    queue = SQLiteApprovalQueue(db_path=db_path)
    try:
        # Allow short ID prefix
        if len(req_id) < 36:
            for rid in list(queue._pending.keys()):
                if rid.startswith(req_id):
                    req_id = rid
                    break

        req = queue.approve(req_id, decided_by=decided_by)
        if req is None:
            print(f"Not found or already decided: {req_id}", file=sys.stderr)
            return 1
        print(f"✅ Approved {req.id}")
        print(f"   agent:  {req.agent_id}")
        print(f"   tool:   {req.tool_name}")
        print(f"   amount: ${req.amount_usd:.2f}")
    finally:
        queue.close()
    return 0


def cmd_approvals_deny(db_path: str, req_id: str, decided_by: str, reason: str) -> int:
    queue = SQLiteApprovalQueue(db_path=db_path)
    try:
        if len(req_id) < 36:
            for rid in list(queue._pending.keys()):
                if rid.startswith(req_id):
                    req_id = rid
                    break

        req = queue.deny(req_id, decided_by=decided_by, reason=reason)
        if req is None:
            print(f"Not found or already decided: {req_id}", file=sys.stderr)
            return 1
        print(f"❌ Denied {req.id}")
        print(f"   agent:  {req.agent_id}")
        print(f"   tool:   {req.tool_name}")
        if reason:
            print(f"   reason: {reason}")
    finally:
        queue.close()
    return 0