# Author: Codex (IIC)
"""Read the G1 motion service status and reported software package version."""


def motion_service_details(client):
    """Display both readings independently using SDK2 B2 RobotStateClient getters."""
    try:
        code, entries = client.ServiceList()
        if code != 0:
            raise RuntimeError(f"RPC code={code}")
        status = next((status for name, status in entries if name == "ai_sport"), None)
        service = "목록에 없음" if status is None else f"status={status}"
    except Exception as error:
        service = f"조회 실패 ({error})"

    try:
        code, package, modules = client.GetPkgVersion()
        if code != 0:
            raise RuntimeError(f"RPC code={code}")
        if not isinstance(package, str) or not package.strip():
            raise ValueError("패키지 버전 문자열 없음")
        version = package.strip()
        if modules.get("ai_sport"):
            version += f" · ai_sport={modules['ai_sport']}"
    except Exception as error:
        version = f"조회 실패 ({error}), Unitree 앱에서 확인"
    return f"robot_state ai_sport {service}\n기체 보고 패키지 버전={version}"
