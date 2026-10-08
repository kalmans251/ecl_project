package com.ecl.monitoring;
import org.springframework.context.annotation.*;
import org.springframework.core.annotation.Order;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
@Configuration
public class SecurityConfiguration {
    @Bean org.springframework.security.web.session.HttpSessionEventPublisher sessionEvents(){return new org.springframework.security.web.session.HttpSessionEventPublisher();}
    @Bean org.springframework.security.crypto.password.PasswordEncoder passwordEncoder(Accounts accounts) { return accounts.passwordEncoder(); }
    @Bean @Order(1) SecurityFilterChain devices(HttpSecurity http, Settings settings, Registry registry) throws Exception {
        return http.securityMatcher("/ws/gateways/**","/api/analytics/**","/api/gateways","/api/events/**")
            .csrf(c -> c.disable()).sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(a -> a.anyRequest().permitAll())
            .addFilterBefore(new Authentication(settings,registry),UsernamePasswordAuthenticationFilter.class).build();
    }
    @Bean SecurityFilterChain browser(HttpSecurity http) throws Exception {
        return http.authorizeHttpRequests(a -> a.requestMatchers("/login.html","/login.js","/api/auth/csrf","/error").permitAll().anyRequest().authenticated())
            .requestCache(c -> c.disable())
            .exceptionHandling(e -> e.authenticationEntryPoint((q,r,x) -> {
                if(q.getRequestURI().startsWith("/api/") || q.getRequestURI().startsWith("/ws/")) r.sendError(401);
                else r.sendRedirect("/login.html");
            }))
            .formLogin(f -> f.loginPage("/login.html").loginProcessingUrl("/api/auth/login")
                .successHandler((q,r,a) -> {r.setContentType("application/json");r.getWriter().write("{\"authenticated\":true}");})
                .failureHandler((q,r,x) -> r.sendError(401)).permitAll())
            .logout(l -> l.logoutUrl("/api/auth/logout").logoutSuccessHandler((q,r,a) -> r.setStatus(204)))
            .headers(h -> h.contentSecurityPolicy(c -> c.policyDirectives("default-src 'self'; script-src 'self' 'unsafe-inline' https://unpkg.com; style-src 'self' 'unsafe-inline' https://unpkg.com https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://*.tile.openstreetmap.org; connect-src 'self'; frame-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'self'")))
            .build();
    }
}
