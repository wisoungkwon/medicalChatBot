package com.medbot;

import com.medbot.repository.PatientRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.model;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * HANDOVER §2-5 에서 손으로 확인했던 보안 시나리오를 테스트로 고정한다.
 *
 * <p>여기서 검증하는 것은 "회귀하면 안 되는" 항목들이다:
 * CSRF 보호, 세션 기반 인가(IDOR 차단), 회원가입 입력 검증, QR 오픈 리다이렉트 차단.
 */
@SpringBootTest
@AutoConfigureMockMvc
class SecurityAndValidationTests {

	@Autowired
	private MockMvc mvc;

	@Autowired
	private PatientRepository patientRepo;

	private static final String VALID_PW = "Abcd1234!";

	@BeforeEach
	void clean() {
		patientRepo.deleteAll();
	}

	private static String signupJson(String id, int age, String gender, String pw) {
		return String.format(
				"{\"id\":\"%s\",\"age\":%d,\"gender\":\"%s\",\"conditions\":\"없음\",\"password\":\"%s\"}",
				id, age, gender, pw);
	}

	private void register(String id) throws Exception {
		mvc.perform(post("/patient/register").with(csrf())
				.contentType(MediaType.APPLICATION_JSON)
				.content(signupJson(id, 30, "m", VALID_PW)))
				.andExpect(status().isOk());
	}

	/** 로그인해서 세션을 얻는다. 이후 요청에 이 세션을 실어 보낸다. */
	private MockHttpSession loginSession(String id) throws Exception {
		MvcResult res = mvc.perform(post("/patient/login").with(csrf())
				.contentType(MediaType.APPLICATION_JSON)
				.content(String.format("{\"id\":\"%s\",\"password\":\"%s\"}", id, VALID_PW)))
				.andExpect(status().isOk())
				.andReturn();
		return (MockHttpSession) res.getRequest().getSession(false);
	}

	// ===== CSRF =====

	@Test
	@DisplayName("CSRF 토큰이 없는 POST 는 403 이다")
	void postWithoutCsrfTokenIsForbidden() throws Exception {
		mvc.perform(post("/patient/login").contentType(MediaType.APPLICATION_JSON)
				.content("{\"id\":\"anyone\",\"password\":\"x\"}"))
				.andExpect(status().isForbidden());
		mvc.perform(post("/patient/logout")).andExpect(status().isForbidden());
		mvc.perform(post("/api/chat").contentType(MediaType.APPLICATION_JSON)
				.content("{\"message\":\"두통\"}"))
				.andExpect(status().isForbidden());
		// /api/diagnosis-history 는 제거됐다(ChatController 가 서버에서 저장한다).
		// 대신 남은 POST 인 회원가입으로 검사한다.
		mvc.perform(post("/patient/register").contentType(MediaType.APPLICATION_JSON)
				.content("{}"))
				.andExpect(status().isForbidden());
	}

	// ===== 회원가입 입력 검증 =====

	@Test
	@DisplayName("정상 회원가입 후 같은 아이디로 다시 가입하면 409")
	void duplicateRegistrationConflicts() throws Exception {
		register("tester01");
		mvc.perform(post("/patient/register").with(csrf())
				.contentType(MediaType.APPLICATION_JSON)
				.content(signupJson("tester01", 30, "m", VALID_PW)))
				.andExpect(status().isConflict());
	}

	@Test
	@DisplayName("잘못된 입력은 500 이 아니라 400 으로 거절된다")
	void invalidRegistrationIsRejectedWith400() throws Exception {
		// 아이디가 컬럼 길이(50)를 넘음 -> 예전에는 저장 시점에 500 이 났다
		mvc.perform(post("/patient/register").with(csrf()).contentType(MediaType.APPLICATION_JSON)
				.content(signupJson("a".repeat(51), 30, "m", VALID_PW)))
				.andExpect(status().isBadRequest());

		// 아이디에 공백
		mvc.perform(post("/patient/register").with(csrf()).contentType(MediaType.APPLICATION_JSON)
				.content(signupJson("ab cd", 30, "m", VALID_PW)))
				.andExpect(status().isBadRequest());

		// 성별이 m/f 가 아님 -> 컬럼 길이 1 을 넘어 예전에는 500
		mvc.perform(post("/patient/register").with(csrf()).contentType(MediaType.APPLICATION_JSON)
				.content(signupJson("tester02", 30, "unknown", VALID_PW)))
				.andExpect(status().isBadRequest());

		// 나이 범위 밖
		mvc.perform(post("/patient/register").with(csrf()).contentType(MediaType.APPLICATION_JSON)
				.content(signupJson("tester03", -5, "m", VALID_PW)))
				.andExpect(status().isBadRequest());

		// 비밀번호 정책 위반 (브라우저 JS 를 우회한 요청)
		mvc.perform(post("/patient/register").with(csrf()).contentType(MediaType.APPLICATION_JSON)
				.content(signupJson("tester04", 30, "m", "1234")))
				.andExpect(status().isBadRequest());
	}

	// ===== 인증 / 인가 =====

	@Test
	@DisplayName("비로그인 상태에서 환자 정보 조회는 401")
	void anonymousCannotReadPatientData() throws Exception {
		mvc.perform(get("/patient/me")).andExpect(status().isUnauthorized());
		mvc.perform(get("/patient/me/history")).andExpect(status().isUnauthorized());
		mvc.perform(get("/patient/someone")).andExpect(status().isUnauthorized());
		mvc.perform(get("/patient/someone/history")).andExpect(status().isUnauthorized());
	}

	@Test
	@DisplayName("로그인해도 타인의 정보는 403 (IDOR 차단)")
	void loggedInUserCannotReadOthers() throws Exception {
		register("alice001");
		register("bob00001");
		MockHttpSession alice = loginSession("alice001");

		mvc.perform(get("/patient/alice001").session(alice)).andExpect(status().isOk());
		mvc.perform(get("/patient/bob00001").session(alice)).andExpect(status().isForbidden());
		mvc.perform(get("/patient/bob00001/history").session(alice)).andExpect(status().isForbidden());
	}

	@Test
	@DisplayName("/patient/me 응답에 비밀번호 해시가 없다")
	void profileDoesNotLeakPasswordHash() throws Exception {
		register("carol001");
		MockHttpSession carol = loginSession("carol001");

		mvc.perform(get("/patient/me").session(carol))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.id").value("carol001"))
				.andExpect(jsonPath("$.passwordHash").doesNotExist())
				.andExpect(jsonPath("$.password").doesNotExist());
	}

	@Test
	@DisplayName("로그아웃하면 세션이 무효화된다")
	void logoutInvalidatesSession() throws Exception {
		register("dave0001");
		MockHttpSession dave = loginSession("dave0001");

		mvc.perform(post("/patient/logout").with(csrf()).session(dave)).andExpect(status().isOk());
		mvc.perform(get("/patient/me").session(dave)).andExpect(status().isUnauthorized());
	}

	@Test
	@DisplayName("틀린 비밀번호와 없는 아이디는 똑같이 401 이다")
	void badCredentialsAreIndistinguishable() throws Exception {
		register("erin0001");

		mvc.perform(post("/patient/login").with(csrf()).contentType(MediaType.APPLICATION_JSON)
				.content("{\"id\":\"erin0001\",\"password\":\"Wrong123!\"}"))
				.andExpect(status().isUnauthorized());
		mvc.perform(post("/patient/login").with(csrf()).contentType(MediaType.APPLICATION_JSON)
				.content("{\"id\":\"nosuchuser\",\"password\":\"Wrong123!\"}"))
				.andExpect(status().isUnauthorized());
	}

	// "남의 아이디로는 진단 이력을 저장할 수 없다" 테스트는 제거했다.
	// 그 검사 대상이던 POST /api/diagnosis-history 자체를 없앴기 때문이다.
	// 이제 진단 이력은 ChatController 가 세션에서 얻은 환자로만 저장하므로,
	// 클라이언트가 patientId 를 지정할 통로가 아예 존재하지 않는다
	// (403 으로 막는 것보다 강한 보장이다).

	// ===== QR =====

	@Test
	@DisplayName("/qrcode 는 app.base-url 하위 주소만 만들어 준다")
	void qrcodeRejectsExternalUrls() throws Exception {
		mvc.perform(get("/qrcode").param("url", "http://localhost:8080/chatbot"))
				.andExpect(status().isOk());
		mvc.perform(get("/qrcode").param("url", "https://evil.example.com"))
				.andExpect(status().isBadRequest());
		// base-url 로 시작하는 것처럼 보이는 다른 도메인
		mvc.perform(get("/qrcode").param("url", "http://localhost:8080.evil.net/x"))
				.andExpect(status().isBadRequest());
	}

	@Test
	@DisplayName("/qr 의 target 은 오픈 리다이렉트가 되지 않는다")
	void qrLandingNormalizesTarget() throws Exception {
		mvc.perform(get("/qr").param("target", "//evil.net"))
				.andExpect(status().isOk())
				.andExpect(model().attribute("fullUrl", "http://localhost:8080/home"));
		mvc.perform(get("/qr").param("target", "http://evil.net"))
				.andExpect(status().isOk())
				.andExpect(model().attribute("fullUrl", "http://localhost:8080/home"));
		mvc.perform(get("/qr").param("target", "chatbot"))
				.andExpect(status().isOk())
				.andExpect(model().attribute("fullUrl", "http://localhost:8080/chatbot"));
	}
}
