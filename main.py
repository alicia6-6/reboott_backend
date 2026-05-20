from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Literal
import os

app = FastAPI(title="Forwarding Visibility MVP API")

# 🔒 CORS 세팅: 프론트엔드(리액트)가 이 서버에 접근할 수 있도록 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 개발 및 테스트 단계에서는 전체 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 1. 데이터 모델 정의 ---
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

# --- 2. 임시 인메모리 데이터베이스 ---
MOCK_DB = [
    {"id": "BL-2026-001", "shipper": "삼성전자", "origin": "부산 (PUS)", "destination": "로스앤젤레스 (LAX)", "status": "운항중", "eta": "2026-05-25"},
    {"id": "BL-2026-002", "shipper": "삼성전자", "origin": "상하이 (SHA)", "destination": "부산 (PUS)", "status": "선적", "eta": "2026-05-28"},
    {"id": "BL-2026-003", "shipper": "현대모비스", "origin": "부산 (PUS)", "destination": "로테르담 (RTM)", "status": "도착", "eta": "2026-05-19"},
]

NOTIFICATION_LOGS = []

# --- 3. API 엔드포인트 구현 ---

@app.get("/api/shipments", response_model=List[Shipment])
def get_shipments():
    """전체 화물 목록 조회"""
    return MOCK_DB

@app.patch("/api/shipments/{shipment_id}", response_model=Shipment)
def update_shipment(shipment_id: str, data: UpdateShipmentInput):
    """운영팀의 화물 상태 및 ETA 업데이트"""
    for shipment in MOCK_DB:
        if shipment["id"] == shipment_id:
            # 비즈니스 로직: ETA가 변경되었을 때 알림 로그 생성
            if shipment["eta"] != data.eta:
                log_msg = f"[알림] {shipment_id} 화물의 ETA가 {shipment['eta']}에서 {data.eta}로 변경되었습니다."
                NOTIFICATION_LOGS.append({"shipment_id": shipment_id, "message": log_msg})
            
            shipment["status"] = data.status
            shipment["eta"] = data.eta
            return shipment
            
    raise HTTPException(status_code=404, detail="화물을 찾을 수 없습니다.")

@app.get("/api/notifications")
def get_notifications():
    """발송된 알림 히스토리 확인"""
    return NOTIFICATION_LOGS

# --- 4. 클라우드(Render) 구동 설정 ---
if __name__ == "__main__":
    import uvicorn
    # Render가 지정해주는 환경변수 PORT를 쓰고, 없으면 기본 8000포트를 씁니다.
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)