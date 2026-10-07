package com.ecl.monitoring;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import org.springframework.boot.context.properties.ConfigurationProperties;
@ConfigurationProperties("monitoring")
public record Settings(String adminToken, String analyticsToken, List<Gateway> gateways, List<Camera> cameras) {
    public record Gateway(String id, String token) {}
    public record Camera(String id, String gatewayId, int railingId) {}
    public Settings {
        gateways = gateways == null ? List.of() : List.copyOf(gateways);
        cameras = cameras == null ? List.of() : List.copyOf(cameras);
        Set<String> tokens = new HashSet<>();
        List<String> all = new ArrayList<>();
        all.add(adminToken); all.add(analyticsToken); gateways.forEach(g -> all.add(g.token()));
        for (String token : all) {
            if (token == null || token.length() < 32 || !tokens.add(token))
                throw new IllegalArgumentException("Set distinct authentication tokens of at least 32 characters");
        }
        Set<String> ids = new HashSet<>();
        for (Gateway g : gateways) if (!validId(g.id()) || !ids.add(g.id()))
            throw new IllegalArgumentException("Invalid or duplicate gateway ID");
        Set<String> cameraIds = new HashSet<>();
        Set<String> rails = new HashSet<>();
        for (Camera c : cameras) if (!validId(c.id()) || !cameraIds.add(c.id()) || !ids.contains(c.gatewayId())
                || c.railingId() < 1 || c.railingId() > 255 || !rails.add(c.gatewayId()+":"+c.railingId()))
            throw new IllegalArgumentException("Invalid or duplicate camera mapping");
    }
    private static boolean validId(String s) { return s != null && s.matches("[a-zA-Z0-9_-]{1,80}"); }
    public Gateway gateway(String id) { return gateways.stream().filter(g -> g.id().equals(id)).findFirst().orElse(null); }
    public static boolean matches(String expected, String actual) {
        return actual != null && MessageDigest.isEqual(expected.getBytes(StandardCharsets.UTF_8), actual.getBytes(StandardCharsets.UTF_8));
    }
}
