# Author: Codex (IIC)
"""Read the G1 motion service status and reported software package version."""

import json


def motion_service_details():
    # The G1 guide specifies the B2 robot_state interface. The pinned B2
    # Python wrapper imports a removed rpc.client_internal module. Use its
    # official API IDs and wire formats with the SDK's maintained RPC client.
    try:
        from unitree_sdk2py.b2.robot_state import robot_state_api as api
        from unitree_sdk2py.rpc.client import Client

        client = Client(api.ROBOT_STATE_SERVICE_NAME, False)
        client.SetTimeout(1.0)
        client._SetApiVerson(api.ROBOT_STATE_API_VERSION)
        client._RegistApi(api.ROBOT_STATE_API_ID_SERVICE_LIST, 0)
        client._RegistApi(api.ROBOT_STATE_API_ID_GET_PKG_VERSION, 0)
    except Exception as error:
        return f"robot_state 조회 실패 ({error})"

    def get(api_id):
        code, payload = client._Call(api_id, "{}")
        if code != 0:
            raise RuntimeError(f"RPC code={code}")
        return json.loads(payload)

    try:
        entries = get(api.ROBOT_STATE_API_ID_SERVICE_LIST)
        if not isinstance(entries, list):
            raise ValueError("서비스 목록 형식 오류")
        sport = next((entry for entry in entries if entry["name"] == "ai_sport"), None)
        service = "목록에 없음" if sport is None else f"status={sport['status']}"
    except Exception as error:
        service = f"조회 실패 ({error})"

    try:
        package = get(api.ROBOT_STATE_API_ID_GET_PKG_VERSION)
        if not isinstance(package.get("packageVersion"), str) or not package["packageVersion"].strip():
            raise ValueError("패키지 버전 문자열 없음")
        version = package["packageVersion"].strip()
        modules = package.get("moduleVersionMap")
        if isinstance(modules, dict) and modules.get("ai_sport"):
            version += f" · ai_sport={modules['ai_sport']}"
    except Exception as error:
        version = f"조회 실패 ({error}), Unitree 앱에서 확인"
    return f"robot_state ai_sport {service}\n기체 보고 패키지 버전={version}"
