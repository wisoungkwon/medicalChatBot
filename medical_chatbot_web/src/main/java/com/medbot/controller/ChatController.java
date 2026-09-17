package com.medbot.controller;

import com.medbot.domain.DiagnosisHistory;
import com.medbot.domain.Patient;
import com.medbot.repository.DiagnosisHistoryRepository;
import com.medbot.repository.PatientRepository;
import jakarta.servlet.http.HttpSession;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

/**
 * 챗봇 요청을 Flask(AI) 서버로 중계하는 컨트롤러.
 *
 * <p>중계 계층을 두는 이유:
 * <ul>
 *   <li>환자 정보(나이/성별/기저질환)를 <b>서버가 DB에서</b> 붙인다.
 *       브라우저가 보낸 값을 그대로 믿으면 위조가 가능하다.</li>
 *   <li>세션으로 본인 확인을 하므로 patientId 를 클라이언트가 지정할 수 없다.</li>
 *   <li>진단 결과 저장까지 한 번의 왕복으로 처리한다.</li>
 * </ul>
 *
 * <p><b>사용 시점:</b> chatbot.js 는 <b>로그인 상태일 때만</b> 이 경로를 쓴다.
 * 비로그인 상태에서는 저장할 대상도 붙일 환자 정보도 없으므로 Flask
 * ({@code app.api-url})를 직접 호출한다.
 */
@RestController
@RequestMapping("/api/chat")
public class ChatController {

	private final PatientRepository patientRepository;
	private final DiagnosisHistoryRepository historyRepository;
	private final RestTemplate restTemplate;

	/** Flask 서버 주소 (예: http://localhost:5050) */
	@Value("${python.api.url}")
	private String pythonApiUrl;

	public ChatController(PatientRepository patientRepository,
			DiagnosisHistoryRepository historyRepository,
			RestTemplateBuilder restTemplateBuilder) {
		this.patientRepository = patientRepository;
		this.historyRepository = historyRepository;
		// 타임아웃을 반드시 준다. 예전에는 new RestTemplate() 이라 무한 대기가 가능했다.
		// 임베딩 + LLM 생성으로 응답이 느리므로 읽기 타임아웃은 넉넉히 둔다.
		this.restTemplate = restTemplateBuilder
				.setConnectTimeout(Duration.ofSeconds(5))
				.setReadTimeout(Duration.ofSeconds(120))
				.build();
	}

	@PostMapping
	public ResponseEntity<?> chat(@RequestBody ChatRequest request, HttpSession session) {
		String loginId = (String) session.getAttribute(PatientController.SESSION_LOGIN_ID);
		if (loginId == null) {
			return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(error("로그인이 필요합니다."));
		}

		String symptoms = request.getMessage() == null ? "" : request.getMessage().trim();
		if (symptoms.isEmpty()) {
			return ResponseEntity.badRequest().body(error("증상을 입력해주세요."));
		}

		// 1) 환자 정보는 세션의 로그인 아이디로 DB에서 조회한다(클라이언트 입력 불신).
		Optional<Patient> opt = patientRepository.findById(loginId);
		if (opt.isEmpty()) {
			return ResponseEntity.status(HttpStatus.NOT_FOUND).body(error("환자 정보를 찾을 수 없습니다."));
		}
		Patient patient = opt.get();

		// 2) Flask 가 기대하는 형식으로 본문 구성 (엔드포인트: /ask_symptoms)
		Map<String, Object> patientInfo = new LinkedHashMap<>();
		patientInfo.put("age", patient.getAge());
		patientInfo.put("gender", patient.getGender());
		patientInfo.put("conditions", patient.getConditions() != null ? patient.getConditions() : "없음");

		Map<String, Object> body = new LinkedHashMap<>();
		body.put("symptom", symptoms);
		body.put("additional_symptoms",
				request.getAdditionalSymptoms() == null ? "" : request.getAdditionalSymptoms().trim());
		body.put("patient", patientInfo);

		HttpHeaders headers = new HttpHeaders();
		headers.setContentType(MediaType.APPLICATION_JSON);

		// 3) Flask 호출
		Map<String, Object> aiResponse;
		try {
			ResponseEntity<Map<String, Object>> pyRes = restTemplate.exchange(
					trimTrailingSlash(pythonApiUrl) + "/ask_symptoms",
					HttpMethod.POST,
					new HttpEntity<>(body, headers),
					new org.springframework.core.ParameterizedTypeReference<Map<String, Object>>() {
					});
			aiResponse = pyRes.getBody();
		} catch (RestClientException e) {
			return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
					.body(error("AI 서버와 통신할 수 없습니다: " + e.getMessage()));
		}

		if (aiResponse == null) {
			return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(error("AI 응답이 없습니다."));
		}

		// 4) 구조화된 진단 결과일 때만 DB에 저장한다.
		//    (추가 정보 요청 / 일반 잡담 응답은 저장 대상이 아니다.)
		Object answer = aiResponse.get("answer");
		if (answer instanceof Map<?, ?> parts) {
			String symptomsToSave = body.get("additional_symptoms").toString().isEmpty()
					? symptoms
					: symptoms + " " + body.get("additional_symptoms");

			DiagnosisHistory history = new DiagnosisHistory();
			history.setPatientId(patient.getId());
			history.setSymptoms(symptomsToSave);
			history.setPredictedDiagnosis(str(parts.get("predictedDiagnosis")));
			history.setDiagnosisDefinition(str(parts.get("diagnosisDefinition")));
			history.setRecommendedDepartment(str(parts.get("recommendedDepartment")));
			history.setPreventionManagement(str(parts.get("preventionManagement")));
			history.setAdditionalInfo(str(parts.get("additionalInfo")));
			history.setMedicine(str(parts.get("medicine")));
			historyRepository.save(history);
		}

		return ResponseEntity.ok(aiResponse);
	}

	// ===== 내부 헬퍼 =====

	private static Map<String, String> error(String message) {
		Map<String, String> m = new HashMap<>();
		m.put("error", message);
		return m;
	}

	private static String str(Object o) {
		return o == null ? "" : o.toString();
	}

	private static String trimTrailingSlash(String s) {
		return s.endsWith("/") ? s.substring(0, s.length() - 1) : s;
	}

	// ===== 요청 DTO =====
	public static class ChatRequest {
		private String message;
		/** 되묻기(needs_more_info) 이후 사용자가 덧붙인 증상 */
		private String additionalSymptoms;

		public String getMessage() {
			return message;
		}

		public void setMessage(String message) {
			this.message = message;
		}

		public String getAdditionalSymptoms() {
			return additionalSymptoms;
		}

		public void setAdditionalSymptoms(String additionalSymptoms) {
			this.additionalSymptoms = additionalSymptoms;
		}
	}
}
