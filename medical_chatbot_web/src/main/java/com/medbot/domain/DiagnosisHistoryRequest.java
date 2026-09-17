package com.medbot.domain;

public class DiagnosisHistoryRequest {
    private String patientId;
    private String symptoms;
    private String predictedDiagnosis;
    private String diagnosisDefinition;
    private String recommendedDepartment;
    private String preventionManagement;
    private String additionalInfo;
    private String medicine;
    
    
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
	
}
