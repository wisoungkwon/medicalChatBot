package com.medbot;

import com.medbot.domain.DiagnosisHistory;
import com.medbot.repository.DiagnosisHistoryRepository;
import com.medbot.repository.PatientRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.test.web.client.MockServerRestTemplateCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.net.ConnectException;
import java.nio.charset.StandardCharsets;
import java.net.SocketTimeoutException;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withServerError;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * {@code POST /api/chat} 이 Flask 실패를 어떻게 사용자에게 전달하는지 고정한다.
 *
 * <p>여기서 지키려는 것은 두 가지다.
 * <ul>
 *   <li><b>내부 정보가 화면으로 새지 않는다.</b> chatbot.js 는 응답의
 *       {@code error} 값을 그대로 챗 말풍선에 출력한다. 예전에는 컨트롤러가
 *       {@code e.getMessage()} 를 그 문구에 이어붙여서, Flask 가 꺼져 있으면
 *       내부 주소가 환자 화면에 보였다. 회귀하기 쉬운 자리라 테스트로 막는다.</li>
 *   <li><b>실패 종류를 구분한다.</b> 읽기 타임아웃은 "기다렸다 다시 하면
 *       될 수도 있다" 는 뜻이므로 504 + 재시도 안내, 연결 실패는 502 다.</li>
 * </ul>
 *
 * <p>Flask 를 실제로 띄우지 않고 {@link MockRestServiceServer} 로 흉내낸다.
 * ChatController 는 {@code RestTemplateBuilder} 로 자기 RestTemplate 을 직접
 * 만들기 때문에 인스턴스를 밖에서 잡을 수 없다. 그래서
 * {@link MockServerRestTemplateCustomizer} 를 빈으로 등록한다 — 빌더가 만드는
 * 모든 템플릿에 자동으로 적용되므로 운영 코드를 테스트용으로 고치지 않아도 된다.
 */
@SpringBootTest
@AutoConfigureMockMvc
class ChatControllerTests {

	/** 테스트 프로퍼티의 python.api.url 과 컨트롤러가 붙이는 경로를 합친 것. */
	private static final String FLASK_URL = "http://localhost:5050/ask_symptoms";

	@TestConfiguration
	static class MockFlaskConfig {
		@Bean
		MockServerRestTemplateCustomizer mockServerCustomizer() {
			return new MockServerRestTemplateCustomizer();
		}
	}

	@Autowired
	private MockMvc mvc;

	@Autowired
	private PatientRepository patientRepo;

	@Autowired
	private DiagnosisHistoryRepository historyRepo;

	@Autowired
	private MockServerRestTemplateCustomizer customizer;

	private MockRestServiceServer flask;
	private MockHttpSession session;

	private static final String PATIENT_ID = "chatuser01";
	private static final String VALID_PW = "Abcd1234!";

	@BeforeEach
	void setUp() throws Exception {
		historyRepo.deleteAll();
		patientRepo.deleteAll();
		flask = customizer.getServer();
		flask.reset();
		session = registerAndLogin();
	}

	private MockHttpSession registerAndLogin() throws Exception {
		mvc.perform(post("/patient/register").with(csrf())
				.contentType(MediaType.APPLICATION_JSON)
				.content(String.format(
						"{\"id\":\"%s\",\"age\":47,\"gender\":\"f\",\"conditions\":\"고혈압\",\"password\":\"%s\"}",
						PATIENT_ID, VALID_PW)))
				.andExpect(status().isOk());

		MvcResult res = mvc.perform(post("/patient/login").with(csrf())
				.contentType(MediaType.APPLICATION_JSON)
				.content(String.format("{\"id\":\"%s\",\"password\":\"%s\"}", PATIENT_ID, VALID_PW)))
				.andExpect(status().isOk())
				.andReturn();
		return (MockHttpSession) res.getRequest().getSession(false);
	}

	private MvcResult chat(String message) throws Exception {
		return mvc.perform(post("/api/chat").with(csrf()).session(session)
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"message\":\"" + message + "\"}"))
				.andReturn();
	}

	/**
	 * 응답 본문을 UTF-8 로 읽는다.
	 *
	 * <p>{@code getContentAsString()} 을 그냥 쓰면 안 된다.
	 * MockHttpServletResponse 는 응답에 charset 이 명시되지 않으면 기본
	 * 인코딩(ISO-8859-1)으로 디코딩해서, 한글 안내 문구가 깨진 문자열로
	 * 돌아온다. 실제 HTTP 응답은 UTF-8 로 정상이므로 앱 문제가 아니라
	 * MockMvc 쪽 사정이다. (JSON 은 규약상 UTF-8 이라 서버가 charset
	 * 파라미터를 붙이지 않는다.)
	 */
	private static String body(MvcResult res) throws Exception {
		return res.getResponse().getContentAsString(StandardCharsets.UTF_8);
	}

	// ===== 실패 전달 =====

	@Test
	@DisplayName("읽기 타임아웃이면 504 와 재시도 안내를 준다")
	void readTimeoutBecomesGatewayTimeout() throws Exception {
		flask.expect(requestTo(FLASK_URL))
				.andRespond(request -> {
					throw new SocketTimeoutException("Read timed out");
				});

		MvcResult res = chat("두통");

		assertThat(res.getResponse().getStatus()).isEqualTo(504);
		String out = body(res);
		assertThat(out).contains("시간이 너무 오래");
		assertThat(out).contains("다시 시도");
		flask.verify();
	}

	@Test
	@DisplayName("연결 실패면 502 와 연결 안내를 준다 (타임아웃 문구와 달라야 한다)")
	void connectionFailureBecomesBadGateway() throws Exception {
		flask.expect(requestTo(FLASK_URL))
				.andRespond(request -> {
					throw new ConnectException("Connection refused: connect");
				});

		MvcResult res = chat("두통");

		assertThat(res.getResponse().getStatus()).isEqualTo(502);
		String out = body(res);
		assertThat(out).contains("연결할 수 없습니다");
		// 타임아웃과 같은 문구로 뭉뚱그리면 안 된다.
		assertThat(out).doesNotContain("시간이 너무 오래");
		flask.verify();
	}

	/**
	 * 이 테스트가 이 클래스의 핵심이다.
	 *
	 * <p>Flask 가 500 과 함께 파이썬 트레이스백을 본문에 실어 보내면,
	 * 그 내용이 응답으로 나가서는 안 된다. 예전 코드는
	 * {@code error("AI 서버와 통신할 수 없습니다: " + e.getMessage())} 였고
	 * {@code HttpServerErrorException} 의 메시지에는 응답 본문이 포함되므로
	 * 트레이스백이 그대로 환자 화면에 출력됐다.
	 */
	@Test
	@DisplayName("Flask 5xx 의 응답 본문(트레이스백)이 사용자 응답으로 새지 않는다")
	void flaskErrorBodyIsNotLeaked() throws Exception {
		String traceback = "Traceback (most recent call last):\n"
				+ "  File \"/app/Backend_Flask_API.py\", line 592, in ask_symptoms\n"
				+ "    answer = chat_with_llm(messages)\n"
				+ "openai.AuthenticationError: Incorrect API key provided: sk-secret123";

		flask.expect(requestTo(FLASK_URL))
				.andRespond(withServerError().body(traceback));

		MvcResult res = chat("두통");

		assertThat(res.getResponse().getStatus()).isEqualTo(502);
		String out = body(res);
		assertThat(out).contains("AI 서버가 응답하지 못했습니다");
		// 내부 정보가 한 조각도 섞이지 않아야 한다.
		assertThat(out).doesNotContain("Traceback");
		assertThat(out).doesNotContain("Backend_Flask_API");
		assertThat(out).doesNotContain("sk-secret123");
		assertThat(out).doesNotContain("openai");
		flask.verify();
	}

	/**
	 * Flask 의 요청 제한(429)만은 502 로 뭉뚱그리지 않는다.
	 *
	 * <p>"AI 서버가 응답하지 못했습니다" 로 내보내면 사용자는 서버 고장으로 알고
	 * 계속 재시도해서 상황을 더 악화시킨다. 기다려야 한다는 것을 알려야 한다.
	 */
	@Test
	@DisplayName("Flask 요청 제한(429)은 사유를 그대로 전달한다")
	void rateLimitIsPassedThrough() throws Exception {
		flask.expect(requestTo(FLASK_URL))
				.andRespond(withStatus(HttpStatus.TOO_MANY_REQUESTS)
						.body("{\"error\":\"요청이 너무 많습니다. 잠시 후 다시 시도해주세요.\"}")
						.contentType(MediaType.APPLICATION_JSON));

		MvcResult res = chat("두통");

		assertThat(res.getResponse().getStatus()).isEqualTo(429);
		String out = body(res);
		assertThat(out).contains("요청이 너무 많습니다");
		// 고장으로 오해하게 만드는 문구가 섞이면 안 된다.
		assertThat(out).doesNotContain("응답하지 못했습니다");
		flask.verify();
	}

	/**
	 * Flask 의 503(AI 모델 혼잡 / 인덱스 미준비)도 502 로 뭉뚱그리지 않는다.
	 *
	 * <p>제공자의 특정 모델이 통째로 막히는 일이 실제로 있었다. 그때 "AI 서버가
	 * 응답하지 못했습니다" 로 내보내면 사용자는 고장으로 알고 곧장 다시 눌러
	 * 같은 벽에 부딪힌다. 기다려야 한다는 것을 알려야 한다.
	 */
	@Test
	@DisplayName("Flask 503(모델 혼잡)은 기다리라는 안내로 전달한다")
	void serviceUnavailableIsPassedThrough() throws Exception {
		flask.expect(requestTo(FLASK_URL))
				.andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE)
						.body("{\"error\":\"지금 AI 모델이 혼잡합니다. 30초쯤 뒤에 다시 시도해주세요.\"}")
						.contentType(MediaType.APPLICATION_JSON));

		MvcResult res = chat("두통");

		assertThat(res.getResponse().getStatus()).isEqualTo(503);
		String out = body(res);
		assertThat(out).contains("혼잡");
		assertThat(out).contains("다시 시도");
		// 고장으로 오해하게 만드는 문구가 섞이면 안 된다.
		assertThat(out).doesNotContain("응답하지 못했습니다");
		flask.verify();
	}

	/**
	 * Flask 는 호출자별로 요청 수를 센다. 이 중계를 거치면 Flask 에게는 모든
	 * 요청이 한 곳(이 서버)에서 오는 것으로 보이므로, 원래 호출자 주소를
	 * 넘겨야 로그인 사용자들이 한 바구니를 공유하지 않는다.
	 */
	@Test
	@DisplayName("Flask 로 원래 호출자 주소를 X-Forwarded-For 로 넘긴다")
	void forwardsClientAddressToFlask() throws Exception {
		flask.expect(requestTo(FLASK_URL))
				.andExpect(header("X-Forwarded-For", MockHttpServletRequest.DEFAULT_REMOTE_ADDR))
				.andRespond(withSuccess("{\"answer\":\"네\"}", MediaType.APPLICATION_JSON));

		chat("두통");

		flask.verify();
	}

	@Test
	@DisplayName("Flask 가 JSON 이 아닌 응답을 주면 502 로 처리한다")
	void nonJsonResponseBecomesBadGateway() throws Exception {
		// ngrok 경고 페이지처럼 HTML 이 돌아오는 경우.
		flask.expect(requestTo(FLASK_URL))
				.andRespond(withSuccess("<html><body>ERR_NGROK_6024</body></html>", MediaType.TEXT_HTML));

		MvcResult res = chat("두통");

		assertThat(res.getResponse().getStatus()).isEqualTo(502);
		String out = body(res);
		assertThat(out).contains("AI 서버가 응답하지 못했습니다");
		assertThat(out).doesNotContain("ERR_NGROK");
		flask.verify();
	}

	@Test
	@DisplayName("실패 응답은 어떤 경우에도 진단 이력을 저장하지 않는다")
	void failuresDoNotSaveHistory() throws Exception {
		flask.expect(requestTo(FLASK_URL)).andRespond(withServerError());

		chat("두통");

		assertThat(historyRepo.findByPatientIdOrderByChatDateDesc(PATIENT_ID)).isEmpty();
		flask.verify();
	}

	// ===== 성공 경로 =====

	@Test
	@DisplayName("구조화된 진단 결과는 세션의 환자로 저장된다")
	void structuredAnswerIsSavedForSessionPatient() throws Exception {
		String answer = """
				{"answer":{
				  "predictedDiagnosis":"급성 기관지염",
				  "diagnosisDefinition":"기관지 점막의 염증",
				  "recommendedDepartment":"내과, 이비인후과",
				  "preventionManagement":"수분 섭취와 휴식",
				  "additionalInfo":"증상이 2주 이상이면 재진",
				  "medicine":"진해거담제"
				}}""";

		// 환자 정보(나이/성별/기저질환)를 서버가 DB 에서 붙여 보내는지도 함께 본다.
		// 브라우저가 보낸 값을 그대로 믿으면 위조가 가능하므로 이게 중요하다.
		flask.expect(requestTo(FLASK_URL))
				.andExpect(method(org.springframework.http.HttpMethod.POST))
				.andExpect(jsonPath("$.symptom").value("기침"))
				.andExpect(jsonPath("$.patient.age").value(47))
				.andExpect(jsonPath("$.patient.gender").value("f"))
				.andExpect(jsonPath("$.patient.conditions").value("고혈압"))
				.andRespond(withSuccess(answer, MediaType.APPLICATION_JSON));

		MvcResult res = chat("기침");

		assertThat(res.getResponse().getStatus()).isEqualTo(200);

		List<DiagnosisHistory> saved = historyRepo.findByPatientIdOrderByChatDateDesc(PATIENT_ID);
		assertThat(saved).hasSize(1);
		assertThat(saved.get(0).getPredictedDiagnosis()).isEqualTo("급성 기관지염");
		assertThat(saved.get(0).getSymptoms()).isEqualTo("기침");
		assertThat(saved.get(0).getMedicine()).isEqualTo("진해거담제");
		flask.verify();
	}

	@Test
	@DisplayName("되묻기(needs_more_info) 응답은 저장하지 않고 그대로 전달한다")
	void needsMoreInfoIsPassedThroughWithoutSaving() throws Exception {
		flask.expect(requestTo(FLASK_URL))
				.andRespond(withSuccess(
						"{\"status\":\"needs_more_info\",\"message\":\"조금 더 알려주세요\"}",
						MediaType.APPLICATION_JSON));

		MvcResult res = chat("아파요");

		assertThat(res.getResponse().getStatus()).isEqualTo(200);
		assertThat(body(res)).contains("needs_more_info");
		assertThat(historyRepo.findByPatientIdOrderByChatDateDesc(PATIENT_ID)).isEmpty();
		flask.verify();
	}

	@Test
	@DisplayName("2xx 인데 본문이 비어 있으면 502 로 처리한다")
	void emptyBodyBecomesBadGateway() throws Exception {
		flask.expect(requestTo(FLASK_URL)).andRespond(withSuccess());

		MvcResult res = chat("두통");

		assertThat(res.getResponse().getStatus()).isEqualTo(502);
		assertThat(body(res)).contains("AI 서버가 응답하지 못했습니다");
		flask.verify();
	}

	// ===== Flask 를 호출하기 전에 막히는 경우 =====

	@Test
	@DisplayName("비로그인 요청은 401 이고 Flask 를 호출하지 않는다")
	void unauthenticatedRequestDoesNotCallFlask() throws Exception {
		mvc.perform(post("/api/chat").with(csrf())
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"message\":\"두통\"}"))
				.andExpect(status().isUnauthorized());

		// expect() 를 하나도 걸지 않았으므로, 호출이 있었다면 여기서 실패한다.
		flask.verify();
	}

	@Test
	@DisplayName("빈 증상은 400 이고 Flask 를 호출하지 않는다")
	void emptySymptomDoesNotCallFlask() throws Exception {
		mvc.perform(post("/api/chat").with(csrf()).session(session)
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"message\":\"   \"}"))
				.andExpect(status().isBadRequest());

		flask.verify();
	}

	@Test
	@DisplayName("세션이 가리키는 환자가 없으면 404 이고 Flask 를 호출하지 않는다")
	void missingPatientDoesNotCallFlask() throws Exception {
		// 로그인 세션은 살아 있는데 환자 행만 지운다.
		patientRepo.deleteAll();

		mvc.perform(post("/api/chat").with(csrf()).session(session)
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"message\":\"두통\"}"))
				.andExpect(status().isNotFound());

		flask.verify();
	}
}
