package com.medbot.controller;

import com.medbot.domain.DiagnosisHistory;
import com.medbot.domain.Patient;
import com.medbot.repository.DiagnosisHistoryRepository;
import com.medbot.repository.PatientRepository;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpSession;
import org.springframework.http.*;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.web.bind.annotation.*;

import java.util.*;
import java.util.regex.Pattern;

@RestController
public class PatientController {

	/** 세션에 로그인 사용자 아이디를 담는 키 */
	public static final String SESSION_LOGIN_ID = "LOGIN_ID";

	// ===== 입력 제약 =====
	// 엔티티 컬럼 길이(id 50 / gender 1 / conditions 500)를 넘기면 저장 시점에
	// DataIntegrityViolationException 이 터져 500 이 나간다. 컨트롤러에서 먼저 막는다.
	private static final int ID_MIN = 4;
	private static final int ID_MAX = 50;
	private static final int CONDITIONS_MAX = 500;
	private static final int AGE_MIN = 1;
	private static final int AGE_MAX = 120;

	/** 공백/제어문자가 섞인 아이디를 거른다. */
	private static final Pattern ID_PATTERN = Pattern.compile("^\\S+$");

	/**
	 * 비밀번호 정책: 영문 + 숫자 + 특수문자를 모두 포함한 8~20자.
	 *
	 * <p>chatbot.js 의 {@code passwordRegex} 와 같은 규칙이다. 클라이언트 검증만
	 * 있으면 curl 한 줄로 우회되므로 서버에서도 동일하게 검사한다.
	 */
	private static final Pattern PASSWORD_PATTERN = Pattern
			.compile("^(?=.*[A-Za-z])(?=.*\\d)(?=.*[!@#$%^&*()_+\\-=\\[\\]{};':\"\\\\|,.<>/?]).{8,20}$");

	/**
	 * 존재하지 않는 아이디로 로그인을 시도할 때 비교 대상으로 쓰는 더미 해시.
	 *
	 * <p>사용자 열거(user enumeration) 방지용이다. 기동할 때 임의의 값으로 한 번만
	 * 만들어 두므로 실제로 맞출 수 있는 비밀번호는 없고, 형식이 올바른 해시라서
	 * {@code matches()} 가 정상적인 비교 비용을 그대로 쓴다.
	 * (형식이 깨진 문자열을 주면 BCrypt 가 즉시 false 를 반환해 시간 차가 그대로 남는다.)
	 */
	private final String dummyHash;

	private final PatientRepository patientRepo;
	private final DiagnosisHistoryRepository historyRepo;
	private final BCryptPasswordEncoder encoder;

	public PatientController(PatientRepository patientRepo, DiagnosisHistoryRepository historyRepo,
			BCryptPasswordEncoder encoder) {
		this.patientRepo = patientRepo;
		this.historyRepo = historyRepo;
		this.encoder = encoder;
		this.dummyHash = encoder.encode(UUID.randomUUID().toString());
	}

	/** 회원가입: 엔티티 + write-only password 사용 */
	@PostMapping("/patient/register")
	public ResponseEntity<String> register(@RequestBody Patient req) {
		if (req.getId() == null || req.getAge() == null || req.getGender() == null || req.getPassword() == null) {
			return ResponseEntity.badRequest().body("필수 항목 누락");
		}

		// 검증은 저장 전에 모두 끝낸다. 예전에는 검증이 전혀 없어서
		//   - 51자 아이디 / "x" 같은 성별 / 음수 나이 -> 컬럼 제약 위반으로 500
		//   - 브라우저 JS 를 우회하면 1자 비밀번호로도 가입
		// 이 가능했다.
		String id = req.getId().trim();
		if (id.length() < ID_MIN || id.length() > ID_MAX || !ID_PATTERN.matcher(id).matches()) {
			return ResponseEntity.badRequest().body("아이디는 공백 없이 " + ID_MIN + "~" + ID_MAX + "자여야 합니다.");
		}
		if (!PASSWORD_PATTERN.matcher(req.getPassword()).matches()) {
			return ResponseEntity.badRequest().body("비밀번호는 영문/숫자/특수문자를 모두 포함한 8~20자여야 합니다.");
		}
		int age = req.getAge();
		if (age < AGE_MIN || age > AGE_MAX) {
			return ResponseEntity.badRequest().body("나이는 " + AGE_MIN + "~" + AGE_MAX + " 사이여야 합니다.");
		}
		String gender = req.getGender().trim().toLowerCase(Locale.ROOT);
		if (!gender.equals("m") && !gender.equals("f")) {
			return ResponseEntity.badRequest().body("성별은 m 또는 f 여야 합니다.");
		}

		String conditions = (req.getConditions() == null || req.getConditions().trim().isEmpty()) ? "없음"
				: req.getConditions().trim();
		if (conditions.length() > CONDITIONS_MAX) {
			return ResponseEntity.badRequest().body("기저질환은 " + CONDITIONS_MAX + "자를 넘을 수 없습니다.");
		}

		if (patientRepo.existsById(id)) {
			return ResponseEntity.status(HttpStatus.CONFLICT).body("이미 존재하는 아이디입니다.");
		}

		Patient p = new Patient();
		p.setId(id);
		p.setAge(age);
		p.setGender(gender);
		p.setConditions(conditions);
		p.setPasswordHash(encoder.encode(req.getPassword())); // 응답에 노출 안 됨

		patientRepo.save(p);
		return ResponseEntity.ok("회원가입이 완료되었습니다.");
	}

	/** 로그인: 간단 Map으로 입력 */
	@PostMapping("/patient/login")
	public ResponseEntity<String> login(@RequestBody Map<String, String> body, HttpServletRequest httpRequest) {
		String rawId = body.get("id");
		String password = body.get("password");
		if (rawId == null || password == null)
			return ResponseEntity.badRequest().body("아이디/비밀번호를 입력하세요.");

		// 가입 때 trim 한 값으로 저장하므로 조회할 때도 똑같이 맞춘다.
		String id = rawId.trim();

		Optional<Patient> opt = patientRepo.findById(id);
		if (opt.isEmpty()) {
			// 존재하지 않는 아이디라도 해시 비교와 비슷한 시간을 쓰게 한다.
			// 곧바로 반환하면 응답 시간 차이로 가입된 아이디를 알아낼 수 있다.
			encoder.matches(password, dummyHash);
			return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("아이디 또는 비밀번호가 올바르지 않습니다.");
		}

		Patient p = opt.get();
		if (p.getPasswordHash() != null && encoder.matches(password, p.getPasswordHash())) {
			// 세션 고정 공격(session fixation) 방지: 로그인 성공 시 세션을 새로 발급한다.
			HttpSession old = httpRequest.getSession(false);
			if (old != null) {
				old.invalidate();
			}
			httpRequest.getSession(true).setAttribute(SESSION_LOGIN_ID, p.getId());
			return ResponseEntity.ok("로그인 성공");
		}
		return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("아이디 또는 비밀번호가 올바르지 않습니다.");
	}

	@PostMapping("/patient/logout")
	public ResponseEntity<String> logout(HttpSession session) {
		session.invalidate();
		return ResponseEntity.ok("로그아웃 되었습니다.");
	}

	/**
	 * 로그인한 본인의 프로필 + 진단 이력.
	 *
	 * 프론트엔드는 이 엔드포인트를 사용해야 한다. 아이디를 URL로 받지 않으므로
	 * 타인의 정보를 조회할 여지가 없다.
	 */
	@GetMapping("/patient/me")
	public ResponseEntity<?> getMe(HttpSession session) {
		String loginId = loginId(session);
		if (loginId == null)
			return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("로그인이 필요합니다.");

		return patientRepo.findById(loginId).<ResponseEntity<?>>map(this::toProfilePayload)
				.orElseGet(() -> ResponseEntity.status(HttpStatus.NOT_FOUND).build());
	}

	/** 로그인한 본인의 진단 이력만 반환 */
	@GetMapping("/patient/me/history")
	public ResponseEntity<?> getMyHistory(HttpSession session) {
		String loginId = loginId(session);
		if (loginId == null)
			return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("로그인이 필요합니다.");

		return ResponseEntity.ok(historyRepo.findByPatientIdOrderByChatDateDesc(loginId));
	}

	/**
	 * 환자 기본 + 히스토리.
	 *
	 * 보안: 예전에는 인증 없이 누구나 아이디만 알면 타인의 나이/성별/기저질환과
	 * 전체 진단 이력을 조회할 수 있었다(IDOR). 이제 로그인한 본인만 조회할 수 있다.
	 * 신규 코드는 /patient/me 를 사용하고, 이 경로는 기존 호환을 위해 남겨 둔다.
	 */
	@GetMapping("/patient/{id}")
	public ResponseEntity<?> getPatient(@PathVariable String id, HttpSession session) {
		String loginId = loginId(session);
		if (loginId == null)
			return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("로그인이 필요합니다.");
		if (!loginId.equals(id))
			return ResponseEntity.status(HttpStatus.FORBIDDEN).body("본인 정보만 조회할 수 있습니다.");

		return patientRepo.findById(id).<ResponseEntity<?>>map(this::toProfilePayload)
				.orElseGet(() -> ResponseEntity.status(HttpStatus.NOT_FOUND).build());
	}

	/** 기존 프론트엔드가 호출하던 경로. 본인 확인 후 이력만 반환한다. */
	@GetMapping("/patient/{id}/history")
	public ResponseEntity<?> getPatientHistory(@PathVariable String id, HttpSession session) {
		String loginId = loginId(session);
		if (loginId == null)
			return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("로그인이 필요합니다.");
		if (!loginId.equals(id))
			return ResponseEntity.status(HttpStatus.FORBIDDEN).body("본인 정보만 조회할 수 있습니다.");

		return ResponseEntity.ok(historyRepo.findByPatientIdOrderByChatDateDesc(id));
	}

	// ===== 내부 헬퍼 =====

	private static String loginId(HttpSession session) {
		return session == null ? null : (String) session.getAttribute(SESSION_LOGIN_ID);
	}

	private ResponseEntity<Map<String, Object>> toProfilePayload(Patient p) {
		List<DiagnosisHistory> history = historyRepo.findByPatientIdOrderByChatDateDesc(p.getId());
		Map<String, Object> out = new LinkedHashMap<>();
		out.put("id", p.getId());
		out.put("age", p.getAge());
		out.put("gender", p.getGender());
		out.put("conditions", p.getConditions());
		out.put("history", history); // 엔티티 그대로(비밀번호 해시는 @JsonIgnore)
		return ResponseEntity.ok(out);
	}
}
