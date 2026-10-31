
/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;
DROP TABLE IF EXISTS `activation_codes`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `activation_codes` (
  `id` int NOT NULL AUTO_INCREMENT,
  `code` varchar(255) NOT NULL,
  `note` text DEFAULT (_utf8mb4''),
  `created_by` int DEFAULT NULL,
  `created_at` text NOT NULL,
  `used_by` int DEFAULT NULL,
  `used_at` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `code` (`code`),
  KEY `idx_activation_used_by` (`used_by`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `app_versions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `app_versions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `version_code` int NOT NULL,
  `version_name` text NOT NULL,
  `release_notes` text DEFAULT (_utf8mb4''),
  `file_name` text NOT NULL DEFAULT (_utf8mb4''),
  `file_size` bigint DEFAULT '0',
  `download_url` text NOT NULL DEFAULT (_utf8mb4''),
  `is_latest` int DEFAULT '0',
  `created_at` text NOT NULL,
  `platform` text NOT NULL DEFAULT (_utf8mb4'android'),
  `sha512` text DEFAULT (_utf8mb4''),
  PRIMARY KEY (`id`),
  KEY `idx_app_versions_latest` (`is_latest`,`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `assignments`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `assignments` (
  `id` int NOT NULL AUTO_INCREMENT,
  `course_id` int DEFAULT NULL,
  `title` text NOT NULL,
  `description` text DEFAULT (_utf8mb4''),
  `deadline` text DEFAULT (_utf8mb4''),
  `is_open` int DEFAULT '1',
  `sort_order` int DEFAULT '0',
  `created_at` text NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_assign_course` (`course_id`,`sort_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `attempts`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `attempts` (
  `id` int NOT NULL AUTO_INCREMENT,
  `exam_id` int NOT NULL,
  `name` text NOT NULL,
  `contact` varchar(255) NOT NULL,
  `score` double DEFAULT '0',
  `total` int DEFAULT '0',
  `correct` int DEFAULT '0',
  `passed` int DEFAULT '0',
  `detail` text DEFAULT (_utf8mb4'{}'),
  `status` text DEFAULT (_utf8mb4'ongoing'),
  `switch_count` int DEFAULT '0',
  `started_at` text NOT NULL,
  `submitted_at` text,
  PRIMARY KEY (`id`),
  KEY `idx_att_contact` (`contact`),
  KEY `idx_att_exam` (`exam_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `challenge_matches`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `challenge_matches` (
  `id` int NOT NULL AUTO_INCREMENT,
  `challenge_id` int NOT NULL,
  `invite_code` varchar(255) NOT NULL,
  `host_id` int NOT NULL,
  `guest_id` int DEFAULT NULL,
  `status` text DEFAULT (_utf8mb4'waiting'),
  `host_elapsed_ms` int DEFAULT '0',
  `guest_elapsed_ms` int DEFAULT '0',
  `host_finished_at` text,
  `guest_finished_at` text,
  `created_at` text NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `invite_code` (`invite_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `challenge_records`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `challenge_records` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `challenge_id` int NOT NULL,
  `passed` int DEFAULT '0',
  `note` text DEFAULT (_utf8mb4''),
  `file_id` int DEFAULT NULL,
  `created_at` text NOT NULL,
  `elapsed_ms` int DEFAULT '0',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `challenges`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `challenges` (
  `id` int NOT NULL AUTO_INCREMENT,
  `title` text NOT NULL,
  `summary` text DEFAULT (_utf8mb4''),
  `content_html` text DEFAULT (_utf8mb4''),
  `difficulty` int DEFAULT '1',
  `deadline` text DEFAULT (_utf8mb4''),
  `is_open` int DEFAULT '1',
  `sort_order` int DEFAULT '0',
  `created_at` text NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `course_progress`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `course_progress` (
  `user_id` int NOT NULL,
  `course_id` int NOT NULL,
  `percent` int DEFAULT '0',
  `status` text DEFAULT (_utf8mb4'learning'),
  `updated_at` text,
  PRIMARY KEY (`user_id`,`course_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `courses`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `courses` (
  `id` int NOT NULL AUTO_INCREMENT,
  `title` text NOT NULL,
  `summary` text DEFAULT (_utf8mb4''),
  `category` text DEFAULT (_utf8mb4''),
  `icon` text DEFAULT (_utf8mb4''),
  `source` text DEFAULT (_utf8mb4'editor'),
  `content_html` text DEFAULT (_utf8mb4''),
  `entry_path` text DEFAULT (_utf8mb4''),
  `sort_order` int DEFAULT '0',
  `is_open` int DEFAULT '1',
  `created_at` text NOT NULL,
  `updated_at` text,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `exams`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `exams` (
  `id` int NOT NULL AUTO_INCREMENT,
  `title` text NOT NULL,
  `description` text DEFAULT (_utf8mb4''),
  `duration_min` int DEFAULT '30',
  `question_count` int DEFAULT '10',
  `tag_filter` text DEFAULT (_utf8mb4''),
  `pass_score` int DEFAULT '60',
  `is_open` int DEFAULT '1',
  `created_at` text NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `feedback`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `feedback` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `title` text DEFAULT (_utf8mb4''),
  `category` text DEFAULT (_utf8mb4''),
  `content` text NOT NULL,
  `status` varchar(255) DEFAULT 'open',
  `created_at` text,
  `updated_at` text,
  `replied_at` text,
  `replied_by` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_feedback_status` (`status`),
  KEY `idx_feedback_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `feedback_images`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `feedback_images` (
  `id` int NOT NULL AUTO_INCREMENT,
  `feedback_id` int NOT NULL,
  `stored_name` text NOT NULL,
  `original_name` text DEFAULT (_utf8mb4''),
  `size` bigint DEFAULT '0',
  `created_at` text,
  PRIMARY KEY (`id`),
  KEY `idx_fb_img_fid` (`feedback_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `feedback_replies`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `feedback_replies` (
  `id` int NOT NULL AUTO_INCREMENT,
  `feedback_id` int NOT NULL,
  `user_id` int NOT NULL,
  `is_admin` int DEFAULT '0',
  `content` text NOT NULL,
  `created_at` text,
  PRIMARY KEY (`id`),
  KEY `idx_fb_reply_fid` (`feedback_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `files`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `files` (
  `id` int NOT NULL AUTO_INCREMENT,
  `kind` varchar(255) NOT NULL DEFAULT 'resource',
  `title` text NOT NULL,
  `description` text DEFAULT (_utf8mb4''),
  `stored_name` text NOT NULL,
  `original_name` text NOT NULL,
  `size` bigint DEFAULT '0',
  `category` text DEFAULT (_utf8mb4''),
  `course_id` int DEFAULT NULL,
  `challenge_id` int DEFAULT NULL,
  `owner_id` int DEFAULT NULL,
  `created_at` text NOT NULL,
  `assignment_id` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_files_kind` (`kind`,`id`),
  KEY `idx_files_owner` (`owner_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `join_requests`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `join_requests` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` text NOT NULL,
  `college` text NOT NULL,
  `contact` text NOT NULL,
  `join_group` int DEFAULT '0',
  `note` text DEFAULT (_utf8mb4''),
  `created_at` text NOT NULL,
  `ip` text DEFAULT (_utf8mb4''),
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `nav_links`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `nav_links` (
  `id` int NOT NULL AUTO_INCREMENT,
  `group_name` varchar(255) NOT NULL DEFAULT '常用链接',
  `title` text NOT NULL,
  `url` text NOT NULL,
  `icon` text DEFAULT (_utf8mb4''),
  `description` text DEFAULT (_utf8mb4''),
  `sort_order` int DEFAULT '0',
  `created_at` text NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_link_group` (`group_name`,`sort_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `post_attachments`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `post_attachments` (
  `id` int NOT NULL AUTO_INCREMENT,
  `post_id` int NOT NULL,
  `file_id` int NOT NULL,
  `created_at` text,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `posts`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `posts` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `title` text NOT NULL,
  `content` text NOT NULL,
  `views` int DEFAULT '0',
  `is_top` int DEFAULT '0',
  `created_at` text NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `practice_logs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `practice_logs` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` text DEFAULT (_utf8mb4''),
  `question_id` int DEFAULT NULL,
  `user_answer` text DEFAULT (_utf8mb4''),
  `is_correct` int DEFAULT '0',
  `created_at` text NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `questions`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `questions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `qtype` text NOT NULL,
  `stem` text NOT NULL,
  `options` text NOT NULL DEFAULT (_utf8mb4'[]'),
  `answer` text NOT NULL,
  `analysis` text DEFAULT (_utf8mb4''),
  `tag` varchar(255) DEFAULT '',
  `difficulty` int DEFAULT '1',
  `created_at` text NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_q_tag` (`tag`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `registrations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `registrations` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` text NOT NULL,
  `college` text NOT NULL,
  `class_name` text NOT NULL,
  `contact` varchar(255) NOT NULL,
  `note` text DEFAULT (_utf8mb4''),
  `created_at` varchar(255) NOT NULL,
  `ip` text DEFAULT (_utf8mb4''),
  PRIMARY KEY (`id`),
  KEY `idx_reg_contact` (`contact`),
  KEY `idx_reg_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `replies`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `replies` (
  `id` int NOT NULL AUTO_INCREMENT,
  `post_id` int NOT NULL,
  `user_id` int NOT NULL,
  `content` text NOT NULL,
  `created_at` text NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `reports`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `reports` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL,
  `name` text NOT NULL,
  `college` text NOT NULL,
  `major_class` text NOT NULL,
  `joined_qq` int DEFAULT '0',
  `status` varchar(255) DEFAULT 'pending',
  `review_note` text DEFAULT (_utf8mb4''),
  `reviewed_by` int DEFAULT NULL,
  `created_at` text NOT NULL,
  `reviewed_at` text,
  PRIMARY KEY (`id`),
  KEY `idx_reports_status` (`status`,`id`),
  KEY `idx_reports_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `scan_logins`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `scan_logins` (
  `token` varchar(255) NOT NULL,
  `user_id` int DEFAULT NULL,
  `status` text DEFAULT (_utf8mb4'pending'),
  `created_at` text NOT NULL,
  `expires_at` text,
  PRIMARY KEY (`token`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `settings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `settings` (
  `k` varchar(255) NOT NULL,
  `v` text,
  PRIMARY KEY (`k`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `study_days`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `study_days` (
  `user_id` int NOT NULL,
  `day` varchar(255) NOT NULL,
  `seconds` int DEFAULT '0',
  PRIMARY KEY (`user_id`,`day`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `users` (
  `id` int NOT NULL AUTO_INCREMENT,
  `username` varchar(255) NOT NULL,
  `phone` varchar(255) NOT NULL,
  `password_hash` text NOT NULL,
  `nickname` text DEFAULT (_utf8mb4''),
  `is_admin` int DEFAULT '0',
  `is_active` int DEFAULT '1',
  `created_at` text NOT NULL,
  `last_login_at` text,
  `quota_mb` int DEFAULT '200',
  `student_no` text DEFAULT (_utf8mb4''),
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`),
  UNIQUE KEY `phone` (`phone`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
DROP TABLE IF EXISTS `videos`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `videos` (
  `id` int NOT NULL AUTO_INCREMENT,
  `course_id` int DEFAULT NULL,
  `title` text NOT NULL,
  `description` text DEFAULT (_utf8mb4''),
  `stored_name` text NOT NULL,
  `original_name` text NOT NULL,
  `size` bigint DEFAULT '0',
  `sort_order` int DEFAULT '0',
  `created_at` text NOT NULL,
  `duration` text DEFAULT (_utf8mb4''),
  `subtitle` text DEFAULT (_utf8mb4''),
  `subtitle_name` text DEFAULT (_utf8mb4''),
  PRIMARY KEY (`id`),
  KEY `idx_videos_course` (`course_id`,`sort_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

