document.addEventListener("DOMContentLoaded", function() {
	/* =========================
	   환경/엔드포인트

	   API_CHAT 은 chatbot.html 의 인라인 스크립트에서 서버 설정(app.api-url)
	   으로 주입된다. 여기서 재선언하면 값이 가려지므로 참조만 한다.
	   (비로그인 상태에서 Flask 를 직접 호출할 때만 쓰인다.)
	========================== */
	if (typeof API_CHAT === "undefined") {
		console.error("API_CHAT 이 정의되지 않았습니다. chatbot.html 의 인라인 스크립트를 확인하세요.");
	}

	/* =========================
	   DOM 캐시
	========================== */
	const byId = (id) => document.getElementById(id);

	// 채팅
	const chat = byId("chat");
	const input = byId("userInput");
	const sendBtn = byId("sendBtn");

	// 프로필/히스토리
	const profileSection = byId("profileSection");
	const historySection = byId("historySection");
	const historyBody = byId("history-table-body");
	const historyEmpty = byId("history-empty");
	const historyCloseBtn = byId("historyCloseBtn");
	const toggleHistoryBtn = byId("toggleHistoryBtn");

	const elId = byId("patient-id");
	const elAge = byId("patient-age");
	const elGender = byId("patient-gender");
	const elCond = byId("patient-conditions");

	// 로그인/회원가입 모달
	const loginBtn = byId("loginBtn");
	const logoutBtn = byId("logoutBtn");
	const loginModal = byId("loginModal");
	const closeLogin = byId("closeLogin");
	const loginForm = byId("loginForm");

	const signupBtn = byId("signupBtn");
	const signupModal = byId("signupModal");
	const closeSignup = byId("closeSignup");
	const signupForm = byId("signupForm");

	// 메뉴
	const menuToggle = byId("menuToggle");
	const sideMenu = byId("sideMenu");
	const menuOverlay = byId("menuOverlay");

	// 글씨/다크모드
	const darkModeBtn = byId("darkModeBtn");
	const body = document.body;

	/* =========================
	   상태
	========================== */
	let currentPatientId = null;
	let isWaitingForMoreInfo = false;
	let originalSymptom = "";

	let cachedHistory = null;
	let historyLoadedOnce = false;
	let isComposing = false; // ⭐ 수정: 한글 IME 조합상태 플래그

	/* =========================
	   CSRF
	   서버(Spring Security)가 XSRF-TOKEN 쿠키를 내려주고,
	   변경 요청에는 X-XSRF-TOKEN 헤더로 되돌려 보내야 한다.
	========================== */
	function getCookie(name) {
		const prefix = name + "=";
		for (const part of document.cookie.split(";")) {
			const c = part.trim();
			if (c.startsWith(prefix)) return decodeURIComponent(c.substring(prefix.length));
		}
		return null;
	}

	/** JSON POST 공통 함수. CSRF 헤더와 쿠키 전송을 항상 포함한다. */
	async function postJson(url, body) {
		const headers = { "Content-Type": "application/json" };
		const token = getCookie("XSRF-TOKEN");
		if (token) headers["X-XSRF-TOKEN"] = token;
		return fetch(url, {
			method: "POST",
			headers,
			credentials: "include",
			body: body === undefined ? undefined : JSON.stringify(body)
		});
	}

	/**
	 * 응답 본문에서 사용자에게 보여줄 한 줄을 꺼낸다.
	 *
	 * 서버는 모든 응답을 JSON 객체로 준다(ApiBody).
	 *   실패 -> { "error": "..." }
	 *   성공 -> { "message": "..." }
	 * 예전에는 /patient/* 만 평문을 돌려줘서 호출부마다 res.text() 와
	 * res.json() 이 섞여 있었다.
	 *
	 * 서버가 죽어 HTML 오류 페이지를 돌려주는 경우처럼 JSON 이 아닐 수도
	 * 있으므로, 파싱 실패는 예외로 터뜨리지 않고 fallback 을 쓴다.
	 */
	async function readApiMessage(res, fallback) {
		try {
			const data = await res.json();
			return data?.error || data?.message || fallback;
		} catch {
			return fallback;
		}
	}

	/* =========================
	   유틸
	========================== */
	function escapeHtml(s) {
		return String(s)
			.replaceAll("&", "&amp;")
			.replaceAll("<", "&lt;")
			.replaceAll(">", "&gt;")
			.replaceAll('"', "&quot;")
			.replaceAll("'", "&#039;");
	}
	function fmt(dt) {
		try {
			return new Date(dt).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
		} catch {
			return dt ?? "";
		}
	}
	function show(el) {
		if (el) el.style.display = "block";
	}
	function hide(el) {
		if (el) el.style.display = "none";
	}

	function clearChatUI() {
		if (!chat) return;
		chat.innerHTML = '<div class="message bot">안녕하세요! 증상을 입력해 주세요.</div>';
	}
	function clearHistoryUI() {
		if (historyBody) historyBody.innerHTML = "";
		if (historyEmpty) historyEmpty.style.display = "none";
		hide(historySection);
		if (toggleHistoryBtn) {
			toggleHistoryBtn.setAttribute("aria-expanded", "false");
			toggleHistoryBtn.textContent = "확장";
		}
	}

	/* =========================
	   프로필/히스토리 렌더
	========================== */
	function renderPatientProfile(data) {
		if (!data) return;
		if (elId) elId.textContent = data.id ?? "";
		if (elAge) elAge.textContent = data.age ?? "";
		if (elGender)
			elGender.textContent =
				data.gender === "m" ? "남자" : data.gender === "f" ? "여자" : data.gender ?? "";
		if (elCond) elCond.textContent = !data.conditions || data.conditions.trim() === "" ? "없음" : data.conditions;
		show(profileSection);
	}

	function renderHistory(list = []) {
		if (!historyBody) return;
		historyBody.innerHTML = "";
		if (!list || list.length === 0) {
			show(historySection);
			show(historyEmpty);
			return;
		}
		hide(historyEmpty);

		// ⭐ 수정: chatDate 내림차순 정렬 보장
		list
			.slice()
			.sort((a, b) => new Date(b.chatDate || 0) - new Date(a.chatDate || 0))
			.forEach((r) => {
				const tr = document.createElement("tr");
				tr.innerHTML = `
          <td>${fmt(r.chatDate)}</td>
          <td>${escapeHtml(r.symptoms ?? "")}</td>
          <td>${escapeHtml(r.predictedDiagnosis ?? "")}</td>
          <td>${escapeHtml(r.recommendedDepartment ?? "")}</td>
          <td>${escapeHtml(r.additionalInfo ?? "")}</td>
        `;
				historyBody.appendChild(tr);
			});
		show(historySection);
	}

	function prependHistoryRow(r) {
		if (!historyBody) return;
		if (historyEmpty) historyEmpty.style.display = "none";
		const tr = document.createElement("tr");
		tr.innerHTML = `
      <td>${fmt(r.chatDate || new Date())}</td>
      <td>${escapeHtml(r.symptoms || "")}</td>
      <td>${escapeHtml(r.predictedDiagnosis || "")}</td>
      <td>${escapeHtml(r.recommendedDepartment || "")}</td>
      <td>${escapeHtml(r.additionalInfo || "")}</td>
    `;
		historyBody.firstChild
			? historyBody.insertBefore(tr, historyBody.firstChild)
			: historyBody.appendChild(tr);
	}

	/* =========================
	   히스토리 지연 로드
	========================== */
	// 서버는 세션으로 본인을 판별하므로 아이디를 URL에 실어 보내지 않는다.
	async function fetchHistoryOnDemand() {
		try {
			const res = await fetch("/patient/me/history", { credentials: "include" });
			if (res.ok) {
				const list = await res.json();
				return Array.isArray(list) ? list : list?.history || [];
			}
		} catch (_) { }
		// 폴백: 프로필 응답에 history 가 함께 온다.
		try {
			const res2 = await fetch("/patient/me", { credentials: "include" });
			if (res2.ok) {
				const data2 = await res2.json();
				return data2?.history || [];
			}
		} catch (_) { }
		return [];
	}
	async function ensureHistoryLoaded() {
		if (!currentPatientId) return [];
		if (historyLoadedOnce && Array.isArray(cachedHistory)) return cachedHistory;
		const list = await fetchHistoryOnDemand();
		cachedHistory = list;
		historyLoadedOnce = true;
		return list;
	}

	/* =========================
	   프로필 불러오기
	========================== */
	async function loadMyProfile(id) {
		// 항상 /patient/me 를 쓴다. 서버가 세션으로 본인을 판별하므로
		// 아이디를 URL에 넣을 필요가 없고, 넣으면 IDOR 표면만 늘어난다.
		const res = await fetch("/patient/me", { credentials: "include" });
		if (!res.ok) throw new Error("프로필을 불러오지 못했습니다.");
		const data = await res.json();
		currentPatientId = data.id || id || null;

		renderPatientProfile(data);
		cachedHistory = Array.isArray(data.history) ? data.history : null;
		historyLoadedOnce = Array.isArray(cachedHistory);
		clearHistoryUI();
	}

	/* =========================
	   히스토리 토글
	========================== */
	toggleHistoryBtn?.addEventListener("click", async () => {
		if (!currentPatientId) return alert("로그인 후 이용해주세요.");
		const expanded = toggleHistoryBtn.getAttribute("aria-expanded") === "true";
		if (expanded) {
			hide(historySection);
			toggleHistoryBtn.setAttribute("aria-expanded", "false");
			toggleHistoryBtn.textContent = "확장";
			return;
		}
		let list = cachedHistory;
		if (!historyLoadedOnce) {
			toggleHistoryBtn.textContent = "로딩중...";
			list = await ensureHistoryLoaded();
		}
		renderHistory(list || []);
		toggleHistoryBtn.setAttribute("aria-expanded", "true");
		toggleHistoryBtn.textContent = "축소";
	});

	historyCloseBtn?.addEventListener("click", () => {
		hide(historySection);
		toggleHistoryBtn?.setAttribute("aria-expanded", "false");
		if (toggleHistoryBtn) toggleHistoryBtn.textContent = "확장";
	});

	/* =========================
	   모달 오픈/닫기 (중복 제거/정리)
	========================== */
	function resetSignupForm() {
		if (!signupForm) return;
		signupForm.reset();
		byId("signupId") && (byId("signupId").value = "");
		byId("signupPwd") && (byId("signupPwd").value = "");
		byId("signupPwdConfirm") && (byId("signupPwdConfirm").value = "");
		byId("signupAge") && (byId("signupAge").value = "");
		byId("signupCondition") && (byId("signupCondition").value = "");
		document.querySelectorAll("input[name='signupGender']").forEach((el) => (el.checked = false));
		const pwd = byId("signupPwd");
		const pwd2 = byId("signupPwdConfirm");
		const icon1 = byId("togglePwd");
		const icon2 = byId("togglePwdConfirm");
		if (pwd) pwd.type = "password";
		if (pwd2) pwd2.type = "password";
		[icon1, icon2].forEach((icon) => {
			if (icon && icon.classList.contains("fa")) {
				icon.classList.add("fa-eye");
				icon.classList.remove("fa-eye-slash");
			}
		});
		const pwMsg = byId("pwMatchMsg");
		if (pwMsg) {
			pwMsg.textContent = "";
			pwMsg.style.display = "none";
			pwMsg.classList.remove("ok", "bad");
		}
		byId("signupId")?.focus();
	}

	function resetLoginForm() {
		if (!loginForm) return;
		loginForm.reset();
		byId("loginId") && (byId("loginId").value = "");
		const lpw = byId("loginPassword");
		const icon = byId("pwToggleLogin");
		if (lpw) lpw.type = "password";
		if (icon && icon.classList.contains("fa")) {
			icon.classList.add("fa-eye");
			icon.classList.remove("fa-eye-slash");
		}
		byId("loginId")?.focus();
	}

	signupBtn?.addEventListener("click", () => {
		if (!signupModal) return;
		resetSignupForm();
		signupModal.style.display = "block";
	});
	closeSignup?.addEventListener("click", () => {
		if (!signupModal) return;
		signupModal.style.display = "none";
		resetSignupForm();
	});

	loginBtn?.addEventListener("click", () => {
		if (!loginModal) return;
		resetLoginForm();
		loginModal.style.display = "block";
	});
	closeLogin?.addEventListener("click", () => {
		if (!loginModal) return;
		loginModal.style.display = "none";
		resetLoginForm();
	});

	window.addEventListener("click", (e) => {
		if (e.target === signupModal) {
			signupModal.style.display = "none";
			resetSignupForm();
		}
		if (e.target === loginModal) {
			loginModal.style.display = "none";
			resetLoginForm();
		}
	});

	/* =========================
	   비밀번호 표시/숨김 + 정책
	========================== */
	function togglePassword(inputEl, iconEl) {
		if (!inputEl || !iconEl) return;
		iconEl.addEventListener("click", () => {
			const toText = inputEl.type === "password";
			inputEl.type = toText ? "text" : "password";
			if (iconEl.classList.contains("fa")) {
				iconEl.classList.toggle("fa-eye");
				iconEl.classList.toggle("fa-eye-slash");
			}
		});
	}
	togglePassword(byId("signupPwd"), byId("togglePwd"));
	togglePassword(byId("signupPwdConfirm"), byId("togglePwdConfirm"));
	togglePassword(byId("loginPassword"), byId("pwToggleLogin"));

	const pwMsg = byId("pwMatchMsg");
	const passwordRegex =
		/^(?=.*[A-Za-z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]).{8,20}$/;
	function updatePwFeedback() {
		const p1 = byId("signupPwd")?.value || "";
		const p2 = byId("signupPwdConfirm")?.value || "";
		pwMsg?.classList.remove("ok", "bad");
		if (pwMsg) pwMsg.style.display = "none";
		if (!p1 && !p2) return;
		if (!passwordRegex.test(p1)) {
			if (pwMsg) {
				pwMsg.textContent = "영문, 숫자, 특수문자를 모두 포함한 8~20자";
				pwMsg.classList.add("bad");
				pwMsg.style.display = "block";
			}
			return;
		}
		if (p2 && p1 !== p2) {
			if (pwMsg) {
				pwMsg.textContent = "비밀번호가 일치하지 않습니다.";
				pwMsg.classList.add("bad");
				pwMsg.style.display = "block";
			}
			return;
		}
		if (p2 && p1 === p2) {
			if (pwMsg) {
				pwMsg.textContent = "비밀번호가 일치합니다.";
				pwMsg.classList.add("ok");
				pwMsg.style.display = "block";
			}
		}
	}
	byId("signupPwd")?.addEventListener("input", updatePwFeedback);
	byId("signupPwdConfirm")?.addEventListener("input", updatePwFeedback);

	/* =========================
	   회원가입/로그인/로그아웃
	========================== */
	signupForm?.addEventListener("submit", async (e) => {
		e.preventDefault();
		const id = byId("signupId")?.value?.trim();
		const age = Number(byId("signupAge")?.value);
		const genderKo = document.querySelector("input[name='signupGender']:checked")?.value;
		const condRaw = byId("signupCondition")?.value?.trim() || "";
		const pwd = byId("signupPwd")?.value || "";
		const pwd2 = byId("signupPwdConfirm")?.value || "";

		// 아래 규칙은 PatientController 의 서버측 검증과 같은 값이다.
		// (서버에도 같은 검사가 있어야 JS 우회를 막을 수 있다.)
		if (!id || !age || !genderKo || !pwd || !pwd2) return alert("필수 항목을 모두 입력해주세요.");
		if (id.length < 4 || id.length > 50 || /\s/.test(id))
			return alert("아이디는 공백 없이 4~50자여야 합니다.");
		if (!Number.isInteger(age) || age < 1 || age > 120)
			return alert("나이는 1~120 사이의 숫자여야 합니다.");
		if (!passwordRegex.test(pwd)) return alert("비밀번호는 영문/숫자/특수문자 포함 8~20자");
		if (pwd !== pwd2) return alert("비밀번호가 일치하지 않습니다.");

		const gender = genderKo === "남" ? "m" : "f";
		const conditions = condRaw === "" ? "없음" : condRaw;

		try {
			const res = await postJson("/patient/register",
				{ id, age, gender, conditions, password: pwd });
			const txt = await readApiMessage(res, res.ok ? "회원가입이 완료되었습니다!" : "회원가입 실패");
			if (!res.ok) throw new Error(txt);
			alert(txt);
			resetSignupForm();
			signupModal.style.display = "none";
		} catch (err) {
			alert(err.message || "오류가 발생했습니다.");
		}
	});

	/** 메뉴의 로그인/회원가입/로그아웃 표시를 로그인 상태에 맞춘다. */
	function setLoggedInUI(loggedIn) {
		if (loginBtn) loginBtn.style.display = loggedIn ? "none" : "list-item";
		if (signupBtn) signupBtn.style.display = loggedIn ? "none" : "list-item";
		if (logoutBtn) logoutBtn.style.display = loggedIn ? "list-item" : "none";
	}

	async function doLogin(id, password) {
		const res = await postJson("/patient/login", { id, password });

		// 성공 여부를 먼저 확인한다. 실패면 여기서 예외로 빠진다.
		// (성공 alert 은 두지 않는다 - 모달이 닫히고 메뉴가 로그아웃으로
		//  바뀌는 것으로 이미 피드백이 되므로 팝업은 불필요하다.)
		if (!res.ok) throw new Error(await readApiMessage(res, "로그인 실패"));

		resetLoginForm?.();
		if (loginModal) loginModal.style.display = "none";
		setLoggedInUI(true);
		return id;
	}

	loginForm?.addEventListener("submit", async (e) => {
		e.preventDefault();
		const id = byId("loginId")?.value?.trim();
		const pw = byId("loginPassword")?.value || "";
		if (!id || !pw) return alert("아이디/비밀번호를 입력하세요.");
		try {
			const loggedId = await doLogin(id, pw);
			await loadMyProfile(loggedId);
		} catch (err) {
			alert(err.message || "로그인 실패");
		}
	});

	logoutBtn?.addEventListener("click", async () => {
		try {
			const res = await postJson("/patient/logout");
			if (!res.ok) throw new Error(await readApiMessage(res, "로그아웃 실패"));
			setLoggedInUI(false);

			currentPatientId = null;
			hide(profileSection);
			clearHistoryUI();
			clearChatUI();
			alert("로그아웃 되었습니다.");
			
			// reload(true) 의 인자는 모든 최신 브라우저에서 무시된다(폐기됨).
			location.reload(); 
			
		} catch (e) {
			alert(e.message || "로그아웃 실패");
		}
	});

	/* =========================
	   채팅 렌더
	========================== */
	function addMessage(text, sender) {
		const msg = document.createElement("div");
		msg.classList.add("message", sender);
		msg.textContent = text;
		chat.appendChild(msg);
		chat.scrollTop = chat.scrollHeight;
		return msg;
	}

	async function showBotAnswer(answer) {
		const msg = document.createElement("div");
		msg.classList.add("message", "bot", "section");

		// LLM 출력은 사용자 입력의 영향을 받으므로 신뢰할 수 없다.
		// marked 는 HTML 을 걸러주지 않기 때문에 DOMPurify 로 정화한 뒤 삽입한다.
		// 둘 중 하나라도 없으면 마크다운을 포기하고 평문으로 표시한다(안전 우선).
		if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
			msg.innerHTML = DOMPurify.sanitize(marked.parse(answer));
		} else {
			msg.textContent = answer;
		}
		chat.appendChild(msg);
		chat.scrollTop = chat.scrollHeight;
	}

	/**
	 * /api/chat 경유로 서버가 이미 DB에 저장한 경우, 화면의 히스토리만 갱신한다.
	 * (중복 저장을 피하기 위해 POST 를 다시 보내지 않는다.)
	 */
	function noteSavedLocally(symptomsText, parts) {
		if (!currentPatientId) return;
		const row = {
			patientId: currentPatientId,
			symptoms: symptomsText,
			predictedDiagnosis: parts.predictedDiagnosis || "",
			diagnosisDefinition: parts.diagnosisDefinition || "",
			recommendedDepartment: parts.recommendedDepartment || "",
			preventionManagement: parts.preventionManagement || "",
			additionalInfo: parts.additionalInfo || "",
			medicine: parts.medicine || "",
			chatDate: new Date().toISOString()
		};
		cachedHistory = Array.isArray(cachedHistory) ? [row, ...cachedHistory] : [row];
		historyLoadedOnce = true;
		if (historySection && historySection.style.display !== "none") {
			prependHistoryRow(row);
		}
	}

	/* =========================
	   메시지 전송
	========================== */
	input?.addEventListener("compositionstart", () => (isComposing = true)); // ⭐ 한글 조합 시작
	input?.addEventListener("compositionend", () => (isComposing = false));  // ⭐ 한글 조합 종료

	input?.addEventListener("keydown", (e) => {
		if (e.key === "Enter" && !e.shiftKey && !isComposing) {
			e.preventDefault();
			sendMessage();
		}
	});
	sendBtn?.addEventListener("click", sendMessage);

	async function sendMessage() {
		const message = input.value.trim();
		if (!message) return;

		// 전송 중 재클릭 방지
		if (sendBtn) sendBtn.disabled = true;

		const userMsg = document.createElement("div");
		userMsg.classList.add("message", "user");
		userMsg.textContent = message;
		chat.appendChild(userMsg);
		chat.scrollTop = chat.scrollHeight;
		input.value = "";

		const loadingMsg = document.createElement("div");
		loadingMsg.classList.add("message", "bot");
		loadingMsg.textContent = "답변 생성 중...";
		chat.appendChild(loadingMsg);

		// 되묻기 흐름: 첫 증상은 originalSymptom 에 남겨두고,
		// 두 번째 입력을 additional_symptoms 로 함께 보낸다.
		let baseSymptom, extraSymptom, symptomsToSave;
		if (isWaitingForMoreInfo) {
			baseSymptom = originalSymptom;
			extraSymptom = message;
			symptomsToSave = (originalSymptom + " " + message).trim();
			isWaitingForMoreInfo = false;
		} else {
			baseSymptom = message;
			extraSymptom = "";
			symptomsToSave = message;
			originalSymptom = message;
		}

		// 로그인 상태면 Spring 을 경유한다. 그러면
		//   - 환자 정보(나이/성별/기저질환)를 서버가 DB에서 채우므로 위조가 불가능하고
		//   - 진단 이력 저장까지 서버가 한 번에 처리한다.
		// 비로그인 상태에서는 저장할 대상이 없으므로 Flask 를 직접 호출한다.
		const useProxy = !!currentPatientId;

		try {
			let r;
			if (useProxy) {
				r = await postJson("/api/chat", {
					message: baseSymptom,
					additionalSymptoms: extraSymptom
				});
			} else {
				// 비로그인: 붙일 환자 정보가 없다. 예전에는 화면의 프로필 영역에서
				// 값을 읽어 보냈지만, 이 분기에서는 프로필이 비어 있어 항상 null 만
				// 전송됐다. Flask 는 patient 가 없으면 증상만으로 처리한다.
				//
				// ngrok-skip-browser-warning: ngrok 무료 플랜은 브라우저 요청에
				// 경고 페이지를 먼저 끼워 넣는다(ERR_NGROK_6024). 사용자가 Flask
				// 주소를 직접 방문할 일이 없어 그 페이지를 넘길 기회가 없으므로,
				// 여기서는 JSON 대신 HTML 이 돌아와 파싱에 실패했다.
				// ngrok 이 아닌 환경에서는 그냥 무시되는 헤더다.
				r = await fetch(API_CHAT, {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
						"ngrok-skip-browser-warning": "1"
					},
					body: JSON.stringify({
						symptom: baseSymptom,
						additional_symptoms: extraSymptom
					})
				});
			}
			const data = await r.json();

			loadingMsg.remove();

			if (data.error) {
				addMessage(data.error, "bot");
			} else if (data.status === "needs_more_info") {
				isWaitingForMoreInfo = true;
				await showBotAnswer(data.message || "추가 증상을 더 알려주세요.");
			} else if (data.answer) {
				if (typeof data.answer === "object" && data.answer.rawResponse) {
					await showBotAnswer(data.answer.rawResponse);
					// 로그인 상태(useProxy)면 서버가 이미 DB에 저장했으므로 화면만 갱신한다.
					// 비로그인 상태에서는 저장할 대상이 없다.
					if (useProxy) noteSavedLocally(symptomsToSave, data.answer);
				} else {
					await showBotAnswer(String(data.answer));
				}
				originalSymptom = "";
			} else {
				addMessage("응답이 없습니다.", "bot");
			}
		} catch (err) {
			loadingMsg.remove();
			addMessage("서버와 통신 중 오류가 발생했습니다.", "bot");
			console.error(err);
		} finally {
			if (sendBtn) sendBtn.disabled = false;
		}
	}

	/* =========================
	   메뉴(햄버거)
	========================== */
	function setMenuHiddenPosition() {
		const menuWidth = sideMenu?.offsetWidth || 240;
		if (sideMenu) sideMenu.style.left = `-${menuWidth + 10}px`;
	}
	setMenuHiddenPosition();
	menuToggle?.addEventListener("click", () => {
		sideMenu?.classList.add("open");
		if (sideMenu) sideMenu.style.left = "0";
		menuOverlay?.classList.add("show");
	});
	menuOverlay?.addEventListener("click", () => {
		setMenuHiddenPosition();
		sideMenu?.classList.remove("open");
		menuOverlay?.classList.remove("show");
	});
	document.querySelectorAll("#sideMenu a").forEach((link) => {
		link.addEventListener("click", () => {
			setMenuHiddenPosition();
			sideMenu?.classList.remove("open");
			menuOverlay?.classList.remove("show");
		});
	});

	/* =========================
	   음성 입력 → 자동 전송
	========================== */
	(function setupAutoSTT() {
		const micBtn = document.querySelector(".mic-btn");
		if (!micBtn || !input || !sendBtn) return;

		const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
		if (!SR) {
			micBtn.addEventListener("click", () => {
				alert("이 브라우저는 음성 인식을 지원하지 않습니다.\nChrome에서 HTTPS(또는 localhost)로 접속해 주세요.");
			});
			return;
		}
		const recognition = new SR();
		recognition.lang = "ko-KR";
		recognition.interimResults = true;
		recognition.continuous = false;

		let recognizing = false;
		let baseValue = "";
		let finalTranscript = "";

		function setBusy(busy) {
			recognizing = busy;
			micBtn.classList.toggle("recording", busy);
			micBtn.disabled = busy;
			micBtn.setAttribute("aria-label", busy ? "음성 입력 중지" : "음성 입력 시작");
			input.placeholder = busy ? "듣는 중..." : "메시지를 입력하세요.";
		}

		micBtn.addEventListener("click", () => {
			if (recognizing) {
				recognition.stop();
				return;
			}
			try {
				baseValue = input.value ? input.value.trim() + " " : "";
				finalTranscript = "";
				recognition.start();
			} catch (e) {
				console.warn("recognition.start() 실패:", e);
				alert("마이크 권한이 필요합니다. 브라우저 설정에서 권한을 허용해 주세요.");
			}
		});

		recognition.onstart = () => setBusy(true);
		recognition.onerror = (e) => {
			console.warn("STT error:", e.error || e);
			if (e.error === "not-allowed" || e.error === "permission-denied") {
				alert("마이크 사용이 거부되었습니다. 브라우저 설정에서 권한을 허용해 주세요.");
			}
		};
		recognition.onresult = (e) => {
			let interim = "";
			for (let i = e.resultIndex; i < e.results.length; i++) {
				const r = e.results[i];
				if (r.isFinal) finalTranscript += r[0].transcript;
				else interim += r[0].transcript;
			}
			input.value = (baseValue + finalTranscript).trimStart();
			input.focus();
			const pos = input.value.length;
			input.setSelectionRange(pos, pos);
		};
		recognition.onend = () => {
			setBusy(false);
			input.value = (baseValue + finalTranscript).trim();
			if (input.value) sendBtn.click();
		};
	})();

	/* =========================
	   글씨 크기/다크모드
	========================== */
	const DEFAULT_FONT_SIZE = 17;
	const minFontSize = 13,
		maxFontSize = 32;

	// 글씨 크기는 접근성 설정이므로 다크모드처럼 저장해 둔다.
	// (예전에는 새로고침할 때마다 기본값으로 돌아갔다.)
	function readFontSize() {
		try {
			const v = parseInt(localStorage.getItem("msg-font-size"), 10);
			if (Number.isFinite(v) && v >= minFontSize && v <= maxFontSize) return v;
		} catch (_) { }
		return DEFAULT_FONT_SIZE;
	}
	let currentFontSize = readFontSize();

	function setMsgFontSize(px) {
		currentFontSize = px;
		document.documentElement.style.setProperty("--msg-font-size", px + "px");
		try {
			localStorage.setItem("msg-font-size", String(px));
		} catch (_) { }
	}
	byId("fontIncrease")?.addEventListener("click", () => {
		if (currentFontSize < maxFontSize) setMsgFontSize(currentFontSize + 2);
	});
	byId("fontDecrease")?.addEventListener("click", () => {
		if (currentFontSize > minFontSize) setMsgFontSize(currentFontSize - 2);
	});
	setMsgFontSize(currentFontSize);

	// 다크모드 상태는 home.html 과 공유한다.
	//   - 저장 키: "prefers-dark" ("true"/"false")
	//   - 클래스는 html(documentElement)과 body 양쪽에 붙인다.
	//     chatbot.css 는 body.dark 를, home.html 은 html.dark 를 기준으로 하기 때문.
	// (예전에는 키가 "darkMode"/"prefers-dark" 로 서로 달라서 페이지를
	//  이동하면 다크모드가 풀렸다.)
	function applyDark(on) {
		document.documentElement.classList.toggle("dark", on);
		body.classList.toggle("dark", on);
		if (darkModeBtn) darkModeBtn.textContent = on ? "☀️" : "🌙";
	}

	function readDarkPref() {
		try {
			const v = localStorage.getItem("prefers-dark");
			if (v !== null) return v === "true";
			// 이전 버전에서 쓰던 키를 한 번 읽어 마이그레이션한다.
			const legacy = localStorage.getItem("darkMode");
			if (legacy !== null) return legacy === "on";
		} catch (_) { }
		// 저장된 선택이 없으면 OS 설정을 따른다. home.html 도 같은 규칙이라
		// 두 페이지를 오갈 때 테마가 바뀌지 않는다. (예전에는 여기만 항상
		// 밝은 테마였다.)
		return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
	}

	applyDark(readDarkPref());

	darkModeBtn?.addEventListener("click", function() {
		const on = !body.classList.contains("dark");
		applyDark(on);
		try {
			localStorage.setItem("prefers-dark", String(on));
			localStorage.removeItem("darkMode");
		} catch (_) { }
	});

	/* =========================
	   세션 복원

	   서버 세션이 아직 살아 있으면 로그인 상태로 되돌린다.
	   예전에는 이 복원이 없어서, 로그인한 뒤 새로고침하면
	     - 메뉴가 다시 "로그인"으로 보이고
	     - currentPatientId 가 null 이라 /api/chat 프록시를 타지 않아
	       환자 정보(나이/성별/기저질환)가 빠진 채 Flask 로 직접 나가고
	     - 진단 이력이 DB 에 저장되지 않았다.
	========================== */
	(async function restoreSession() {
		try {
			await loadMyProfile();        // 401 이면 예외 -> 비로그인 상태로 둔다
			setLoggedInUI(true);
		} catch (_) {
			setLoggedInUI(false);
		}
	})();
});
