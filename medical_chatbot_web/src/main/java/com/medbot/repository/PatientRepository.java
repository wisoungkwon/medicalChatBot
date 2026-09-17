package com.medbot.repository;

import org.springframework.data.jpa.repository.JpaRepository;

import com.medbot.domain.Patient;

public interface PatientRepository extends JpaRepository<Patient, String> {
}
