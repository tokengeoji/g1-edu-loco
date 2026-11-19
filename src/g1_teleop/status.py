# Author: Codex (IIC)
"""Read-only G1 sport service details for the one-shot status command."""

import json


def status_details(client):
    """Keep each optional reading available even when the other RPC fails."""
    try:
        code, version = client.GetServerApiVersion()
        if code != 0:
            raise RuntimeError(f"RPC code={code}")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("버전 문자열 없음")
        api = version.strip()
    except Exception as error:
        api = f"조회 실패 ({error})"

    try:
        from unitree_sdk2py.g1.loco.g1_loco_api import ROBOT_API_ID_LOCO_GET_FSM_MODE

        # SDK2 Python registers this getter but exposes no wrapper. The SDK2
        # C++ GetFsmMode reads the integer 'data' field from the same reply.
        code, reply = client._Call(ROBOT_API_ID_LOCO_GET_FSM_MODE, "{}")
        if code != 0:
            raise RuntimeError(f"RPC code={code}")
        data = json.loads(reply)
        if not isinstance(data, dict) or type(data.get("data")) is not int:
            raise ValueError("정수 상태값 없음")
        mode = data["data"]
        description = {0: "정적 상태", 1: "동적 상태"}.get(mode, "알 수 없는 상태")
        state = f"{mode} ({description})"
    except Exception as error:
        state = f"조회 실패 ({error})"

    return f"보행 서비스 API 버전={api}\nGetFsmMode={state}"
