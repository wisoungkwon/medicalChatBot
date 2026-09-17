package com.medbot.controller;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.ui.Model;

@Controller
public class HomeController {

	/** 브라우저가 직접 호출하는 Flask 주소. chatbot.html 의 API_CHAT 으로 주입된다. */
	@Value("${app.api-url}")
	private String apiUrl;

	/**
	 * 루트 경로.
	 *
	 * <p>매핑이 없어 404 가 났다. 공유받은 사람은 대개 루트로 먼저 들어오므로
	 * 랜딩으로 넘겨 준다.
	 */
	@GetMapping("/")
	public String root() {
		return "redirect:/home";
	}

	/** 랜딩 페이지. AI 를 직접 호출하지 않으므로 apiUrl 을 넘기지 않는다. */
	@GetMapping("/home")
	public String home() {
		return "home";
	}

	@GetMapping("/chatbot")
	public String chatbot(Model model) {
		model.addAttribute("apiUrl", apiUrl);
		return "chatbot";
	}
}
