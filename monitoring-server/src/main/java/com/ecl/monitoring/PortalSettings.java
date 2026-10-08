package com.ecl.monitoring;
import org.springframework.boot.context.properties.ConfigurationProperties;
@ConfigurationProperties("portal")
public record PortalSettings(String bootstrapUser, String bootstrapPassword, String smsKey,
        String smsSecret, String smsFrom, String codecUrl, String codecToken) {}
