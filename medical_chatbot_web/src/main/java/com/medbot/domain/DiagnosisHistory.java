package com.medbot.domain;

import jakarta.persistence.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "diagnosis_history", indexes = @Index(name = "idx_patient_chat_date", columnList = "patient_id, chat_date"))
public class DiagnosisHistory {

	@Id
	@GeneratedValue(strategy = GenerationType.IDENTITY)
	private Long id;

	@Column(name = "patient_id", nullable = false)
	private String patientId;

	@Column(columnDefinition = "TEXT")
	private String symptoms;

	@Column(name = "predicted_diagnosis", columnDefinition = "TEXT")
	private String predictedDiagnosis;

	@Column(name = "diagnosis_definition", columnDefinition = "TEXT")
	private String diagnosisDefinition;

	@Column(name = "recommended_department", columnDefinition = "TEXT")
	private String recommendedDepartment;

	@Column(name = "prevention_management", columnDefinition = "TEXT")
	private String preventionManagement;

	@Column(name = "additional_info", columnDefinition = "TEXT")
	private String additionalInfo;

	@Column(name = "medicine", columnDefinition = "TEXT")
	private String medicine;
	
	@Column(name = "chat_date")
	private LocalDateTime chatDate;

	@PrePersist
    protected void onCreate() {
        if (this.chatDate == null) {
            this.chatDate = LocalDateTime.now(); // ✅ 저장 직전 서버 시간이 들어감
        }
    }
	
	// Getter / Setter
	public Long getId() {
		return id;
	}

	public void setId(Long id) {
		this.id = id;
	}

	public String getPatientId() {
		return patientId;
	}

	public void setPatientId(String patientId) {
		this.patientId = patientId;
	}

	public String getSymptoms() {
		return symptoms;
	}

	public void setSymptoms(String symptoms) {
		this.symptoms = symptoms;
	}

	public String getPredictedDiagnosis() {
		return predictedDiagnosis;
	}

	public void setPredictedDiagnosis(String predictedDiagnosis) {
		this.predictedDiagnosis = predictedDiagnosis;
	}

	public String getDiagnosisDefinition() {
		return diagnosisDefinition;
	}

	public void setDiagnosisDefinition(String diagnosisDefinition) {
		this.diagnosisDefinition = diagnosisDefinition;
	}

	public String getRecommendedDepartment() {
		return recommendedDepartment;
	}

	public void setRecommendedDepartment(String recommendedDepartment) {
		this.recommendedDepartment = recommendedDepartment;
	}

	public String getPreventionManagement() {
		return preventionManagement;
	}

	public void setPreventionManagement(String preventionManagement) {
		this.preventionManagement = preventionManagement;
	}

	public String getAdditionalInfo() {
		return additionalInfo;
	}

	public void setAdditionalInfo(String additionalInfo) {
		this.additionalInfo = additionalInfo;
	}

	public String getMedicine() {
	    return medicine;
	}

	public void setMedicine(String medicine) {
	    this.medicine = medicine;
	}
	
	public LocalDateTime getChatDate() {
		return chatDate;
	}

	public void setChatDate(LocalDateTime chatDate) {
		this.chatDate = chatDate;
	}
}
