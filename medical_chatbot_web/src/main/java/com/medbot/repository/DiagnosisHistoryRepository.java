package com.medbot.repository;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import com.medbot.domain.DiagnosisHistory;

import java.util.List;

@Repository
// 엔티티의 @Id 는 Long 이다. 예전에는 Integer 로 선언되어 있어서
// findById/deleteById 를 쓰는 순간 타입 불일치로 깨질 상태였다.
public interface DiagnosisHistoryRepository extends JpaRepository<DiagnosisHistory, Long> {

	/**
	 * 최신순 진단 이력.
	 *
	 * <p>이력이 아주 많아지면 페이징이 필요하다. 지금은 화면이 전체를 한 번에
	 * 그리므로 List 로 둔다. (예전에는 쓰이지 않는 findTop5.../findAllByPatientId
	 * 두 개가 함께 선언돼 있었다.)
	 */
	List<DiagnosisHistory> findByPatientIdOrderByChatDateDesc(String patientId);
}
