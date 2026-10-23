package com.ecl.monitoring;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.scheduling.annotation.EnableScheduling;
@SpringBootApplication
@EnableConfigurationProperties({Settings.class, PortalSettings.class})
@EnableScheduling
public class Application {
    public static void main(String[] args) {
        if (args.length == 1 && args[0].equals("--codec-self-test")) {
            try (var codec = new Codec2(new PortalSettings(null,null,null,null,null,System.getenv("CODEC2_LIBRARY")))) {
                if (!codec.available()) throw new IllegalStateException(codec.unavailableReason());
                String call=java.util.UUID.randomUUID().toString(), epoch=java.util.UUID.randomUUID().toString();
                byte[] bits=codec.convert(call,epoch,true,new byte[2560]);
                if (bits.length!=48 || codec.convert(call,epoch,false,bits).length!=2560) throw new IllegalStateException("Codec2 geometry mismatch");
                System.out.println("Codec2 native self-test OK");
            }
            return;
        }
        SpringApplication.run(Application.class, args);
    }
}
