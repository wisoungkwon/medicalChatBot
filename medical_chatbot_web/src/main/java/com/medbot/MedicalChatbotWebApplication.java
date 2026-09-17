package com.medbot;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.security.servlet.UserDetailsServiceAutoConfiguration;

/**
 * 이 앱의 인증은 각 컨트롤러가 {@code HttpSession} 으로 직접 처리한다
 * (SecurityConfig 참고). Spring Security 의 기본 사용자 자동설정을 끄지 않으면
 * 기동할 때마다 쓰지도 않는 임시 비밀번호가 로그에 찍혀 혼란을 준다.
 */
@SpringBootApplication(exclude = UserDetailsServiceAutoConfiguration.class)
public class MedicalChatbotWebApplication {

	public static void main(String[] args) {
		SpringApplication.run(MedicalChatbotWebApplication.class, args);
	}

}
