package com.medbot.controller;

import com.medbot.domain.DiagnosisHistory;
import com.medbot.domain.DiagnosisHistoryRequest;
import com.medbot.repository.DiagnosisHistoryRepository;
import jakarta.servlet.http.HttpSession;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
// @CrossOrigin(전체 허용)을 제거했다. 프론트엔드가 같은 오리진에서
// 세션 쿠키로 호출하므로 교차 출처 허용이 필요 없고, 세션 기반 API에
// 무제한 CORS 를 열어두면 CSRF 위험만 커진다.
public class DiagnosisHistoryController {

	private final DiagnosisHistoryRepository repo;

	public DiagnosisHistoryController(DiagnosisHistoryRepository repo) {
		this.repo = repo;
	}

	@PostMapping("/api/diagnosis-history")
	public ResponseEntity<?> save(@RequestBody DiagnosisHistoryRequest request, HttpSession session) {
	    String loginId = (String) session.getAttribute(PatientController.SESSION_LOGIN_ID);
	    if (loginId == null)
	        return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("로그인이 필요합니다.");

	    String patientId = request.getPatientId();
	    if (patientId == null || !loginId.equals(patientId)) {
	        return ResponseEntity.status(HttpStatus.FORBIDDEN).body("본인 계정의 기록만 저장할 수 있습니다.");
	    }

	    DiagnosisHistory dh = new DiagnosisHistory();
	    dh.setPatientId(patientId);
	    dh.setSymptoms(request.getSymptoms());
	    dh.setPredictedDiagnosis(request.getPredictedDiagnosis());
	    dh.setDiagnosisDefinition(request.getDiagnosisDefinition());
	    dh.setRecommendedDepartment(request.getRecommendedDepartment());
	    dh.setPreventionManagement(request.getPreventionManagement());
	    dh.setAdditionalInfo(request.getAdditionalInfo());
	    dh.setMedicine(request.getMedicine()); // ✅ 수정된 DTO의 getter 사용
	    
	    DiagnosisHistory saved = repo.save(dh);
	    return ResponseEntity.ok(saved);
	}
}
