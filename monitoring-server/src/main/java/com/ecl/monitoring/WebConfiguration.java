package com.ecl.monitoring;
import org.springframework.context.annotation.*;
import org.springframework.web.socket.config.annotation.*;
import org.springframework.web.socket.server.standard.ServletServerContainerFactoryBean;
@Configuration
@EnableWebSocket
public class WebConfiguration implements WebSocketConfigurer {
    private final DeviceSocket socket;private final Voice voice;private final CameraSocket camera;private final RadarSocket radar;
    public WebConfiguration(DeviceSocket socket,Voice voice,CameraSocket camera,RadarSocket radar) { this.socket=socket;this.voice=voice;this.camera=camera;this.radar=radar; }
    @Override public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(radar,"/ws/operator/radar/*").addInterceptors(new org.springframework.web.socket.server.support.HttpSessionHandshakeInterceptor());
        registry.addHandler(camera,"/ws/cameras/*");
        registry.addHandler(socket,"/ws/gateways/*");
        registry.addHandler(voice,"/ws/operator/voice/*").addInterceptors(new org.springframework.web.socket.server.support.HttpSessionHandshakeInterceptor());
    }
    @Bean public ServletServerContainerFactoryBean webSocketContainer() {
        var container=new ServletServerContainerFactoryBean();
        container.setMaxTextMessageBufferSize(4096); container.setMaxBinaryMessageBufferSize(4096);
        container.setMaxSessionIdleTimeout(60000L); container.setAsyncSendTimeout(1000L);
        return container;
    }
}
