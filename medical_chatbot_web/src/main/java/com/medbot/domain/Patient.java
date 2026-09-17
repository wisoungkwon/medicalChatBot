package com.medbot.domain;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonProperty;
import jakarta.persistence.*;
import java.util.Objects;

@Entity
@Table(name = "patient")
public class Patient {

	@Id
	@Column(name = "id", length = 50, nullable = false)
	private String id;

	@Column(name = "age", nullable = false)
	private Integer age;

	// "m" or "f"
	@Column(name = "gender", length = 1, nullable = false)
	private String gender;

	@Column(name = "conditions", length = 500, nullable = false)
	private String conditions;

	/** DB 저장용 비밀번호 해시(응답에서 숨김) */
	@JsonIgnore
	@Column(name = "password_hash", length = 100)
	private String passwordHash;

	/** 회원가입 때만 받는 평문 비밀번호(컬럼 아님, 쓰기 전용) */
	@Transient
	@JsonProperty(access = JsonProperty.Access.WRITE_ONLY)
	private String password;

	// --- getters/setters ---

	public String getId() {
		return id;
	}

	public void setId(String id) {
		this.id = id;
	}

	public Integer getAge() {
		return age;
	}

	public void setAge(Integer age) {
		this.age = age;
	}

	public String getGender() {
		return gender;
	}

	public void setGender(String gender) {
		this.gender = gender;
	}

	public String getConditions() {
		return conditions;
	}

	public void setConditions(String conditions) {
		this.conditions = conditions;
	}

	public String getPasswordHash() {
		return passwordHash;
	}

	public void setPasswordHash(String passwordHash) {
		this.passwordHash = passwordHash;
	}

	public String getPassword() {
		return password;
	}

	public void setPassword(String password) {
		this.password = password;
	}

	@Override
	public boolean equals(Object o) {
		if (this == o)
			return true;
		if (!(o instanceof Patient))
			return false;
		Patient patient = (Patient) o;
		return Objects.equals(id, patient.id);
	}

	@Override
	public int hashCode() {
		return Objects.hash(id);
	}
}
