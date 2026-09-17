package com.medbot.controller;

import com.medbot.domain.DiagnosisHistory;
import com.medbot.domain.Patient;
import com.medbot.repository.DiagnosisHistoryRepository;
import com.medbot.repository.PatientRepository;
import jakarta.servlet.http.HttpSession;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import java.net.SocketTimeoutException;
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

	private static final Logger log = LoggerFactory.getLogger(ChatController.class);

	/**
	 * 사용자에게 보여줄 오류 문구.
	 *
	 * <p><b>이 문자열들은 개발자용 로그가 아니라 환자가 읽는 안내문이다.</b>
	 * chatbot.js 는 응답의 {@code error} 값을 그대로 챗 말풍선에 출력한다
	 * (chatbot.js 의 {@code if (data.error) addMessage(data.error, "bot")}).
	 * 따라서 두 가지를 지킨다:
	 * <ul>
	 *   <li>예외 메시지({@code e.getMessage()})나 Flask 응답 본문을 섞지 않는다.
	 *       내부 주소와 파이썬 트레이스백이 화면에 그대로 노출되고, 환자에게는
	 *       아무 도움도 되지 않는다. 원인은 서버 로그에만 남긴다.</li>
	 *   <li>다시 시도하면 될 상황인지를 문구로 구분해 알려준다.</li>
	 * </ul>
	 */
	private static final String MSG_LOGIN_REQUIRED = "로그인이 필요합니다.";
	private static final String MSG_EMPTY_SYMPTOM = "증상을 입력해주세요.";
	private static final String MSG_PATIENT_NOT_FOUND = "환자 정보를 찾을 수 없습니다. 다시 로그인해주세요.";
	private static final String MSG_AI_TIMEOUT = "답변을 만드는 데 시간이 너무 오래 걸립니다. 잠시 후 다시 시도해주세요.";
	private static final String MSG_AI_UNREACHABLE = "AI 서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.";
	private static final String MSG_AI_FAILED = "AI 서버가 응답하지 못했습니다. 잠시 후 다시 시도해주세요.";

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
			return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(error(MSG_LOGIN_REQUIRED));
		}

		String symptoms = request.getMessage() == null ? "" : request.getMessage().trim();
		if (symptoms.isEmpty()) {
			return ResponseEntity.badRequest().body(error(MSG_EMPTY_SYMPTOM));
		}

		// 1) 환자 정보는 세션의 로그인 아이디로 DB에서 조회한다(클라이언트 입력 불신).
		Optional<Patient> opt = patientRepository.findById(loginId);
		if (opt.isEmpty()) {
			// 세션은 살아 있는데 환자 행이 없다. 정상 경로로는 나올 수 없는 상태라
			// (계정 삭제 후 세션이 남았거나 DB 를 갈아끼운 경우) 로그로 남긴다.
			log.warn("세션의 로그인 아이디로 환자를 찾지 못했다. loginId={}", loginId);
			return ResponseEntity.status(HttpStatus.NOT_FOUND).body(error(MSG_PATIENT_NOT_FOUND));
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
		//    실패를 세 갈래로 나눈다. 사용자에게 줄 안내와 로그에 남길 내용이 서로 다르다.
		String url = trimTrailingSlash(pythonApiUrl) + "/ask_symptoms";
		Map<String, Object> aiResponse;
		try {
			ResponseEntity<Map<String, Object>> pyRes = restTemplate.exchange(
					url,
					HttpMethod.POST,
					new HttpEntity<>(body, headers),
					new org.springframework.core.ParameterizedTypeReference<Map<String, Object>>() {
					});
			aiResponse = pyRes.getBody();
		} catch (HttpStatusCodeException e) {
			// Flask 가 응답은 했지만 4xx/5xx 다. 본문에 파이썬 트레이스백이 실려 오는
			// 경우가 있어 로그에만 남기고 화면으로는 내보내지 않는다.
			log.error("Flask 오류 응답. url={} status={} body={}",
					url, e.getStatusCode(), e.getResponseBodyAsString());
			return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(error(MSG_AI_FAILED));
		} catch (ResourceAccessException e) {
			// 연결 자체가 안 됐거나(서버 미기동) 읽기 타임아웃이다.
			// 타임아웃은 "조금 기다렸다 다시 하면 될 수도 있다" 는 뜻이라 문구를 구분한다.
			boolean timedOut = e.getCause() instanceof SocketTimeoutException;
			log.error("Flask 호출 실패. url={} timedOut={}", url, timedOut, e);
			return timedOut
					? ResponseEntity.status(HttpStatus.GATEWAY_TIMEOUT).body(error(MSG_AI_TIMEOUT))
					: ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(error(MSG_AI_UNREACHABLE));
		} catch (RestClientException e) {
			// 나머지 — 주로 JSON 이 아닌 응답이 와서 역직렬화에 실패한 경우.
			log.error("Flask 응답 처리 실패. url={}", url, e);
			return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(error(MSG_AI_FAILED));
		}

		if (aiResponse == null) {
			log.error("Flask 가 2xx 를 주었지만 본문이 비어 있다. url={}", url);
			return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(error(MSG_AI_FAILED));
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
