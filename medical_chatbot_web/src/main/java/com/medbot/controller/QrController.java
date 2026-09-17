package com.medbot.controller;

import com.google.zxing.BarcodeFormat;
import com.google.zxing.WriterException;
import com.google.zxing.client.j2se.MatrixToImageWriter;
import com.google.zxing.qrcode.QRCodeWriter;
import com.google.zxing.common.BitMatrix;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.*;
import org.springframework.ui.Model;

import java.io.IOException;
import java.io.ByteArrayOutputStream;

@Controller
public class QrController {

	@Value("${app.base-url}")
	private String appBaseUrl;

	/**
	 * QR 이미지 생성.
	 *
	 * 보안: 예전에는 임의의 url 파라미터를 그대로 QR로 만들어 주었기 때문에,
	 * 이 서버를 피싱용 QR 생성기로 쓸 수 있었다(신뢰된 도메인이 만든 QR처럼 보임).
	 * 이제 app.base-url 로 시작하는 URL만 허용한다.
	 */
	@GetMapping(value = "/qrcode", produces = MediaType.IMAGE_PNG_VALUE)
	@ResponseBody
	public ResponseEntity<byte[]> qrcode(@RequestParam String url) throws WriterException, IOException {
		if (!isAllowed(url)) {
			return ResponseEntity.badRequest().build();
		}

		int size = 320;
		QRCodeWriter writer = new QRCodeWriter();
		BitMatrix matrix = writer.encode(url, BarcodeFormat.QR_CODE, size, size);

		try (ByteArrayOutputStream baos = new ByteArrayOutputStream()) {
			MatrixToImageWriter.writeToStream(matrix, "PNG", baos);
			return ResponseEntity.ok().contentType(MediaType.IMAGE_PNG).body(baos.toByteArray());
		}
	}

	// ✅ /qr 엔드포인트는 최종 URL을 완성하여 뷰로 전달합니다.
	@GetMapping("/qr")
	public String qrLanding(@RequestParam(defaultValue = "/home") String target, Model model) {
		String path = normalizeTarget(target);
		String fullUrl = trimTrailingSlash(appBaseUrl) + path;

		model.addAttribute("fullUrl", fullUrl);
		model.addAttribute("qrImgSrc", "/qrcode?url=" + fullUrl);
		model.addAttribute("targetPath", path);
		return "qr";
	}

	// ===== 내부 헬퍼 =====

	/** app.base-url 하위 URL 만 QR로 만들어 준다. */
	private boolean isAllowed(String url) {
		if (url == null || appBaseUrl == null || appBaseUrl.isBlank()) {
			return false;
		}
		String base = trimTrailingSlash(appBaseUrl);
		// base 자체 또는 base/... 만 허용 (base 로 시작하는 다른 도메인 차단:
		// 예) base=https://a.com 일 때 https://a.com.evil.net 은 거부)
		return url.equals(base) || url.startsWith(base + "/");
	}

	/**
	 * target 을 이 서버 내부의 경로로 강제한다.
	 * 스킴/호스트가 포함된 값(//evil.net, http://evil.net)은 오픈 리다이렉트가
	 * 되므로 받아들이지 않고 기본값으로 되돌린다.
	 */
	private String normalizeTarget(String target) {
		if (target == null || target.isBlank()) {
			return "/home";
		}
		String t = target.trim();
		if (t.contains("://") || t.startsWith("//") || t.contains("\\")) {
			return "/home";
		}
		return t.startsWith("/") ? t : "/" + t;
	}

	private static String trimTrailingSlash(String s) {
		return s.endsWith("/") ? s.substring(0, s.length() - 1) : s;
	}
}
