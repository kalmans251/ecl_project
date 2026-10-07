package com.ecl.monitoring;
import java.io.IOException;
import java.util.concurrent.ConcurrentHashMap;
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
@Component
public class Authentication extends OncePerRequestFilter {
    private final Settings settings;
    private final ConcurrentHashMap<String, Bucket> buckets = new ConcurrentHashMap<>();
    private static class Bucket { long minute; int count; synchronized boolean allow() {
        long current = System.nanoTime()/60_000_000_000L;
        if (minute != current) { minute=current; count=0; }
        return ++count <= 600;
    }}
    public Authentication(Settings settings) { this.settings = settings; }
    @Override protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String path=request.getRequestURI(), expected=null, identity="";
        if (path.startsWith("/ws/gateways/")) {
            String id=path.substring("/ws/gateways/".length());
            Settings.Gateway gateway=settings.gateway(id);
            if (gateway != null) { expected=gateway.token(); identity="gateway:"+id; }
            // Native device endpoint: browser cookies/Origin are never accepted as credentials.
            if (request.getHeader("Origin") != null || !request.getMethod().equals("GET")) {
                response.sendError(403); return;
            }
        } else if (path.equals("/api/analytics/events") && request.getMethod().equals("POST")) {
            expected=settings.analyticsToken(); identity="analytics";
        } else if (request.getMethod().equals("GET") && (path.equals("/api/gateways") || path.startsWith("/api/events/"))) {
            expected=settings.adminToken(); identity="admin";
        } else { response.sendError(404); return; }
        String header=request.getHeader("Authorization");
        String supplied=header != null && header.startsWith("Bearer ") ? header.substring(7) : null;
        if (expected == null || !Settings.matches(expected,supplied)) { response.sendError(401); return; }
        if (!buckets.computeIfAbsent(identity,k -> new Bucket()).allow()) { response.sendError(429); return; }
        if (request.getContentLengthLong() > 4096) { response.sendError(413); return; }
        // Also bound bodies without Content-Length (chunked requests).
        HttpServletRequestWrapper bounded = new HttpServletRequestWrapper(request) {
            @Override public ServletInputStream getInputStream() throws IOException {
                ServletInputStream input=request.getInputStream();
                return new ServletInputStream() {
                    int total;
                    public int read() throws IOException {
                        int value=input.read();
                        if (value >= 0 && ++total > 4096) throw new IOException("Request body exceeds limit");
                        return value;
                    }
                    public boolean isFinished() { return input.isFinished(); }
                    public boolean isReady() { return input.isReady(); }
                    public void setReadListener(ReadListener listener) { input.setReadListener(listener); }
                };
            }
        };
        chain.doFilter(bounded,response);
    }
}
