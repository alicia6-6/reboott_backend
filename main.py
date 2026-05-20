from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Literal, Optional
import os

app = FastAPI(title="Forwarding Visibility MVP API")

# 🔒 CORS 세팅: 프론트엔드(리액트)의 도메인 제한 없이 안전하게 연결을 허용합니다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 실무 배포 시에는 특정 도메인만 명시하는 것이 보안상 좋으나, MVP 검증을 위해 전체 허용합니다.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- [스키마] 데이터 모델 정의 ---
ShipmentStatus = Literal['선적', '운항중', '도착', '통관 완료']

class Shipment(BaseModel):
    id: str
    shipper: str
    origin: str
    destination: str
    status: ShipmentStatus
    eta: str

class UpdateShipmentInput(BaseModel):
    status: ShipmentStatus
    eta: str

class LoginInput(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    success: bool
    token: str
    role: Literal['shipper', 'admin']
    shipper_name: Optional[str] = None  # 화주일 경우에만 특정 소속 이름 반환

# --- [DB] 임시 인메모리 데이터베이스 ---
MOCK_DB = [
    {"id": "BL-2026-001", "shipper": "삼성전자", "origin": "부산 (PUS)", "destination": "로스앤젤레스 (LAX)", "status": "운항중", "eta": "2026-05-25"},
    {"id": "BL-2026-002", "shipper": "삼성전자", "origin": "상하이 (SHA)", "destination": "부산 (PUS)", "status": "선적", "eta": "2026-05-28"},
    {"id": "BL-2026-003", "shipper": "현대모비스", "origin": "부산 (PUS)", "destination": "로테르담 (RTM)", "status": "도착", "eta": "2026-05-19"},
]

NOTIFICATION_LOGS = []

# --- [API] 엔드포인트 구현 ---

@app.post("/api/login", response_model=LoginResponse)
def login(data: LoginInput):
    """테스트용 심플 인증 엔드포인트 (RBAC 뼈대)"""
    # 1. 화주(Client) 계정 검증
    if data.username == "shipper" and data.password == "password123":
        return {
            "success": True, 
            "token": "mock-jwt-token-shipper-value", 
            "role": "shipper", 
            "shipper_name": "삼성전자"
        }
    # 2. 포워더 운영팀(Admin) 계정 검증
    elif data.username == "admin" and data.password == "password123":
        return {
            "success": True, 
            "token": "mock-jwt-token-admin-value", 
            "role": "admin"
        }
    
    raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 일치하지 않습니다.")

@app.get("/api/shipments", response_model=List[Shipment])
def get_shipments():
    """전체 화물 목록 조회"""
    return MOCK_DB

@app.patch("/api/shipments/{shipment_id}", response_model=Shipment)
def update_shipment(shipment_id: str, data: UpdateShipmentInput):
    """운영팀의 화물 상태 및 ETA 업데이트"""
    for shipment in MOCK_DB:
        if shipment["id"] == shipment_id:
            # 비즈니스 로직: ETA가 기존 값과 다르게 변경되었을 때만 알림 로그 생성
            if shipment["eta"] != data.eta:
                log_msg = f"[알림] {shipment_id} 화물의 ETA가 {shipment['eta']}에서 {data.eta}로 변경되었습니다."
                NOTIFICATION_LOGS.append({"shipment_id": shipment_id, "message": log_msg})
            
            shipment["status"] = data.status
            shipment["eta"] = data.eta
            return shipment
            
    raise HTTPException(status_code=404, detail="해당 화물 데이터를 찾을 수 없습니다.")

@app.get("/api/notifications")
def get_notifications():
    """발송된 알림 내역 히스토리 로그 조회"""
    return NOTIFICATION_LOGS

# --- [구동] 클라우드 배포용 인프라 포트 바인딩 ---
if __name__ == "__main__":
    import uvicorn
    # Render 클라우드가 동적으로 부여하는 포트 환경변수를 수용합니다.
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)