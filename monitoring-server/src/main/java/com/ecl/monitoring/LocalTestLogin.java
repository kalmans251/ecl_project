package com.ecl.monitoring;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import org.springframework.web.filter.OncePerRequestFilter;

/** Opt-in for a directly accessed loopback test server. */
final class LocalTestLogin extends OncePerRequestFilter {
    private final AuthenticationManager authentication;
    private final String password;
    private final HttpSessionSecurityContextRepository sessions=new HttpSessionSecurityContextRepository();

    LocalTestLogin(AuthenticationManager authentication,String password){
        this.authentication=authentication;
        this.password=password;
    }

    @Override protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,
            FilterChain chain) throws ServletException,IOException {
        String path=request.getRequestURI();
        if("GET".equals(request.getMethod()) && ("/".equals(path)||"/login.html".equals(path))
                && "127.0.0.1".equals(request.getRemoteAddr()) && "127.0.0.1".equals(request.getLocalAddr())
                && "127.0.0.1".equals(request.getServerName())
                && request.getHeader("Forwarded")==null && request.getHeader("X-Forwarded-For")==null
                && request.getHeader("X-Forwarded-Host")==null
                && SecurityContextHolder.getContext().getAuthentication()==null){
            try {
                var user=authentication.authenticate(UsernamePasswordAuthenticationToken.unauthenticated("admin",password));
                if(request.getSession(false)!=null)request.changeSessionId();
                var context=SecurityContextHolder.createEmptyContext();
                context.setAuthentication(user);
                SecurityContextHolder.setContext(context);
                sessions.saveContext(context,request,response);
                if("/login.html".equals(path)){response.sendRedirect("/");return;}
            }catch(AuthenticationException ignored){
                // Wrong test password: fall back to the normal login screen.
            }
        }
        chain.doFilter(request,response);
    }
}
