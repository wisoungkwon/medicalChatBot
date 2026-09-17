package com.medbot.controller;

import java.util.Collections;
import java.util.Map;

/**
 * API 응답 본문을 만드는 헬퍼.
 *
 * <p>예전에는 컨트롤러마다 형식이 달랐다. ChatController 는
 * {@code {"error": "..."}} 를 돌려주는데 PatientController 는 평문 문자열을
 * 돌려주고 있었다. 프론트엔드도 그에 맞춰 한쪽은 {@code res.json()},
 * 다른 쪽은 {@code res.text()} 로 읽어야 했다.
 *
 * <p>형식이 갈리면 두 가지가 불편하다.
 * <ul>
 *   <li>호출부가 엔드포인트마다 읽는 방법을 기억해야 한다.</li>
 *   <li>나중에 에러 코드 같은 필드를 덧붙일 때 평문 쪽은 늘릴 자리가 없다.</li>
 * </ul>
 *
 * <p>그래서 모든 응답을 JSON 객체로 통일한다.
 * 실패는 {@code error}, 성공 안내는 {@code message} 키를 쓴다.
 *
 * <p><b>주의:</b> 여기 담기는 문자열은 사용자가 그대로 읽는 안내문이다.
 * 예외 메시지({@code e.getMessage()})나 스택트레이스를 넣지 말 것 —
 * 내부 구조가 화면에 노출되고 사용자에게는 도움이 되지 않는다.
 * 원인은 서버 로그에만 남긴다.
 */
final class ApiBody {

	private ApiBody() {
	}

	/** 실패 응답 본문: {@code {"error": message}} */
	static Map<String, String> error(String message) {
		return Collections.singletonMap("error", message);
	}

	/** 성공 안내 본문: {@code {"message": message}} */
	static Map<String, String> message(String message) {
		return Collections.singletonMap("message", message);
	}
}
