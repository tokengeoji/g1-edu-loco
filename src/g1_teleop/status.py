# Author: Codex (IIC)
"""Read-only G1 sport service details for the one-shot status command."""


def status_details(client):
    """Keep each optional reading available even when the other RPC fails."""
    try:
        version = client.GetServerApiVersion()
        if not isinstance(version, str) or not version.strip():
            raise ValueError("버전 문자열 없음")
        api = version.strip()
    except Exception as error:
        api = f"조회 실패 ({error})"

    try:
        code, mode = client.GetFsmMode()
        if code != 0:
            raise RuntimeError(f"RPC code={code}")
        if type(mode) is not int:
            raise ValueError("정수 상태값 없음")
        description = {0: "정적 상태", 1: "동적 상태"}.get(mode, "알 수 없는 상태")
        state = f"{mode} ({description})"
    except Exception as error:
        state = f"조회 실패 ({error})"

    return f"보행 서비스 API 버전={api}\nGetFsmMode={state}"
