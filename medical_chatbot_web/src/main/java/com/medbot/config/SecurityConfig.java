package com.medbot.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.csrf.CookieCsrfTokenRepository;
import org.springframework.security.web.csrf.CsrfTokenRequestAttributeHandler;

/**
 * 보안 설정.
 *
 * <p>목적은 <b>CSRF 보호</b>다. 이 앱은 세션 쿠키로 로그인 상태를 유지하는데,
 * CSRF 보호가 없으면 외부 사이트가 사용자의 브라우저를 이용해
 * {@code /patient/logout}, {@code /api/chat} 같은 POST 를
 * 위조 호출할 수 있다.
 *
 * <p><b>인증/인가는 기존 방식을 그대로 유지한다.</b> 각 컨트롤러가
 * {@code HttpSession} 의 {@code LOGIN_ID} 를 직접 확인하고 있으므로
 * 여기서는 모든 경로를 {@code permitAll} 로 두고 필터 단계의 인가는 걸지 않는다.
 * (Spring Security 의 로그인 폼/기본 인증도 쓰지 않는다.)
 * 나중에 인가를 Spring Security 로 옮기려면 이 클래스를 수정하면 된다.
 *
 * <p>CSRF 토큰 전달 방식은 SPA/AJAX 용 표준 구성이다:
 * <ul>
 *   <li>서버가 {@code XSRF-TOKEN} 쿠키를 내려준다 (HttpOnly 아님 → JS 가 읽을 수 있음)</li>
 *   <li>클라이언트가 {@code X-XSRF-TOKEN} 헤더로 되돌려 보낸다
 *       (chatbot.js 의 {@code postJson()} 이 자동 처리)</li>
 * </ul>
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig {

	@Bean
	public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
		CookieCsrfTokenRepository tokenRepository = CookieCsrfTokenRepository.withHttpOnlyFalse();

		// Spring Security 6 는 기본적으로 CSRF 토큰을 지연 로딩하는데, 그러면
		// 토큰을 실제로 참조하기 전까지 쿠키가 내려가지 않는다.
		// csrfRequestAttributeName 을 null 로 두면 즉시 로딩으로 바뀌어
		// 첫 GET 응답부터 XSRF-TOKEN 쿠키가 설정된다.
		CsrfTokenRequestAttributeHandler requestHandler = new CsrfTokenRequestAttributeHandler();
		requestHandler.setCsrfRequestAttributeName(null);

		http
				// 모든 경로 허용: 인가는 각 컨트롤러가 세션으로 직접 판단한다.
				.authorizeHttpRequests(auth -> auth.anyRequest().permitAll())

				// CSRF 보호 (GET/HEAD/OPTIONS 등 안전한 메서드는 자동 제외)
				.csrf(csrf -> csrf
						.csrfTokenRepository(tokenRepository)
						.csrfTokenRequestHandler(requestHandler))

				// 기본 로그인 화면/HTTP Basic 팝업을 쓰지 않는다.
				// (로그인은 /patient/login 이 직접 처리)
				.formLogin(form -> form.disable())
				.httpBasic(basic -> basic.disable())
				.logout(logout -> logout.disable());

		return http.build();
	}

	/**
	 * 비밀번호 해시 인코더.
	 *
	 * <p>이전에는 각 컨트롤러가 {@code new BCryptPasswordEncoder()} 를 직접
	 * 만들어 썼다. 빈으로 등록해 두면 설정(강도 등)을 한 곳에서 바꿀 수 있다.
	 */
	@Bean
	public BCryptPasswordEncoder passwordEncoder() {
		return new BCryptPasswordEncoder();
	}
}
