package com.ecl.monitoring;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
class WeatherAutomationTest {
 @Test void mapsCurrentWeatherToExistingPatterns(){
  assertEquals("clear",WeatherAutomation.category(0));assertEquals("clear",WeatherAutomation.category(2));
  assertEquals("cloudy",WeatherAutomation.category(3));assertEquals("cloudy",WeatherAutomation.category(45));
  assertEquals("rain",WeatherAutomation.category(61));assertEquals("rain",WeatherAutomation.category(95));
  assertEquals("snow",WeatherAutomation.category(73));assertEquals("snow",WeatherAutomation.category(86));
 }
 @Test void disablingRequiresSiteWritePermissionAndDoesNotSendDeviceCommand() throws Exception {
  JdbcTemplate db=mock(JdbcTemplate.class);Accounts accounts=mock(Accounts.class);Registry registry=mock(Registry.class);Commands commands=mock(Commands.class);
  when(registry.rail("r")).thenReturn(Map.of("SITE_ID","s"));
  WeatherAutomation auto=new WeatherAutomation(db,accounts,registry,commands);
  try{assertTrue(auto.set(()->"operator","r",new WeatherAutomation.Mode(false)).isEmpty());
   verify(accounts).permit("operator","s",true);verify(db).update("UPDATE weather_auto SET enabled=FALSE WHERE rail_id=?","r");verifyNoInteractions(commands);
  }finally{auto.close();}
 }
 @Test void automaticWeatherRequiresRealInstallationCoordinates(){
  JdbcTemplate db=mock(JdbcTemplate.class);Accounts accounts=mock(Accounts.class);Registry registry=mock(Registry.class);Commands commands=mock(Commands.class);
  when(registry.rail("r")).thenReturn(Map.of("SITE_ID","s"));
  WeatherAutomation auto=new WeatherAutomation(db,accounts,registry,commands);
  try{assertThrows(RuntimeException.class,()->auto.set(()->"operator","r",new WeatherAutomation.Mode(true)));verifyNoInteractions(commands);}
  finally{auto.close();}
 }
}
